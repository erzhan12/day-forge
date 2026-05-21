# RULES.md

Project-specific patterns, pitfalls, and conventions discovered during development.
This is a living document — update it as new patterns emerge.

## Secrets & Environment Files

- Never commit `.env` files. `.gitignore` excludes `.env` and `.env.*`, with `!.env.example` carved out so a sanitized template can be committed.
- Secrets belong in env vars, not code or fixtures. See `backend/day_forge/settings.py` and the env var list in `CLAUDE.md` (`LLM_API_KEY`, `DJANGO_SECRET_KEY`, etc.).
- Before committing, sanity-check with `git ls-files | grep -E '(^|/)\.env'` — should return nothing except `.env.example` if one exists.
- User commands sent to `POST /api/ai/schedules/<date>/command/` are logged verbatim to `AIInteraction` (capped at 2 KB). Treat this table as sensitive; don't paste real secrets into the command bar while testing.

## Dev Server Restart Modes

- `make run` keeps Django's default autoreloader enabled. Use `make run-manual` when code edits should not restart the backend automatically; it passes `--noreload` to `manage.py runserver`.

## XSS / Output Escaping

- Block titles flow user → DB → Vue. Vue's `{{ ... }}` text interpolation auto-escapes, and there is **no `v-html` usage** in `frontend/src/`. Do **not** call `django.utils.html.escape()` on titles before saving — Vue would then render `&lt;` literally, mangling legitimate inputs containing `<`, `>`, or `&`. Escape at the render boundary, not the storage boundary, and only if `v-html` is ever introduced.
- LLM-supplied strings are shape/length-validated in `backend/ai/schemas.py`. Control chars below 0x20 (excluding `\t\n\r`) are rejected to keep titles safe for downstream CSV exports and log scrapers.

## AI Undo Registration

- A `200 OK` from the AI command endpoint does **not** always mean the schedule changed. The LLM may return `actions: []` with an explanation (e.g. "outside working hours") — this is a successful interaction with zero mutations.
- Undo must be registered only when `result.data.blocks` actually differs from the pre-submit snapshot. The comparison lives in `_scheduleChanged()` in `frontend/src/components/CommandBar.vue`.
- When `data.blocks` is missing from the response, treat as no change (do not push undo) — this is the safe default.

## Schedule.status flip rules

Full transition matrix (post-Phase 6):

```
draft  ──user edits any block──▶  active  ──Mark reviewed click──▶  reviewed
                                  ▲ │                                    │
                                  │ └────────────────────────────────────┘
                                  └── any subsequent edit on reviewed ────┘
                                       (mark_active_on_edit)
```

- `Schedule.status` flips `draft → active` AND `reviewed → active` on every forward-mutating endpoint: `create_block`, `block_detail` PATCH, `block_detail` DELETE, `reorder_blocks`, and `ai_command` (only when `len(parsed_actions) > 0`). The single helper for both directions is `Schedule.mark_active_on_edit()` in `backend/schedules/models.py` (replaces the Phase-5 `mark_active_if_draft`).
- `Schedule.mark_reviewed_if_active()` flips `active → reviewed` (forward direction). Refuses on `draft` — a never-edited day cannot be reviewed (analytics would be meaningless on auto-draft data the user never touched).
- `restore_blocks` (the undo target) does **not** flip status. Calling it with the previous block list shouldn't pretend the user just made a fresh edit. Concretely: undoing a freshly auto-generated draft (`restore_blocks([])`) leaves `status="draft"`, so the regenerate button reappears.
- `ai_generate_draft` does **not** flip status. The badge stays "Draft" until the user actually edits.
- `ai_command` returning `actions: []` is a successful no-op (RULES.md / undo gating already documented this). Status flipping must follow the same gate, otherwise an LLM responding with "I don't understand" silently promotes a draft to active.

### `mark_active_on_edit` MUST use a DB-conditional UPDATE, not a Python `self.status` check

Critical: the helper is implemented as

```python
type(self).objects.filter(
    pk=self.pk,
    status__in=[self.Status.DRAFT, self.Status.REVIEWED],
).update(status=self.Status.ACTIVE)
```

NOT as `if self.status in (...): self.save()`. Reason: a concurrent `mark_reviewed` may flip the row to `reviewed` between the time a `block_detail` PATCH loaded its `Schedule` instance and the time `mark_active_on_edit` is called. The in-memory `self.status` would still say `active` and a Python-side check would short-circuit the flip, leaving the DB row frozen-reviewed with stale snapshot data. The conditional UPDATE evaluates its WHERE clause against current DB state at lock-acquisition time, so it correctly re-flips the row. The regression test `TestMarkActiveOnEdit::test_stale_instance_recovery` in `backend/tests/test_status_flow.py` pins this contract.

Both helpers also sync `self.status` after a successful UPDATE so callers that re-read the in-memory copy see the new value without a refetch.

## Analytics: frozen-vs-recompute review snapshot

- `analytics_view` (`GET /analytics/<date>/`) **recomputes the `DailyReview` row on every visit** while `Schedule.status != "reviewed"`. Toggle a checkbox on `/schedule/<date>/`, navigate to `/analytics/<date>/`, the panel reflects the toggle immediately. No polling, no WebSocket — just a recompute on each GET.
- Once `status == "reviewed"`, the row is **frozen**. The view serves the persisted snapshot verbatim; `updated_at` no longer advances.
- Editing any block on a `reviewed` schedule flips `status → active` via `mark_active_on_edit`, which makes the next analytics visit recompute. End state is always "fresh frozen snapshot" or "active + recomputed-on-next-visit", never "frozen + stale".
- `mark_reviewed` is **hard-idempotent**: a retry against an already-reviewed schedule returns the persisted snapshot without parsing the body, acquiring the lock, or recomputing. `updated_at` is identical between two calls — pinned by `test_idempotent_returns_same_snapshot_unchanged_updated_at`.

## `mark_reviewed` parses the request body AFTER the under-lock status check

The endpoint is hard-idempotent on `REVIEWED`: a retry should always succeed and return the persisted snapshot, regardless of payload. If the body were parsed before the status check, a network retry with a corrupted body would 400 on `JSONDecodeError` even though the previous attempt already succeeded. Order in `backend/analytics/views.py:mark_reviewed`:

1. `reject_oversized_body` (413) — independent of status.
2. Date parse (400).
3. Schedule lookup (404).
4. Pre-lock status check — REVIEWED returns the snapshot without touching the body.
5. `transaction.atomic()` + `select_for_update().get()` on the parent `Schedule` row.
6. Re-check status under the lock — REVIEWED still returns the snapshot without parsing.
7. ONLY when `status == ACTIVE` under the lock do we parse and validate the body, then recompute + persist + flip status.

This pattern is pinned by `test_idempotent_tolerates_malformed_body_on_reviewed`. See also "Locking an empty child queryset locks nothing" — the parent-row lock is required because `TimeBlock` may be empty.

## Streak walker semantics

- `compute_streak(user)` walks calendar dates backward from yesterday up to `ANALYTICS_STREAK_WINDOW_DAYS` (default 30).
- **Gap day** (no `Schedule` row for that date) → hard break. Rationale: the user didn't plan that day, so the streak ends.
- **Zero-block schedule** ("rest day") → skip — doesn't count, doesn't break.
- **Day with blocks** → use `DailyReview.completion_rate` if the row exists (cheap read), otherwise compute on the fly via `compute_review_stats` (no DB write — keeps the streak accurate for users who plan well but rarely open analytics).
- A day at or above `ANALYTICS_STREAK_THRESHOLD` (default 0.8) counts; below → break.

## Skipped-tasks semantics (today vs past)

`SkippedTasks.vue` mirrors `compute_review_stats` exactly:

- **Past day** → every uncompleted block is shown.
- **Today** → only blocks whose `end_time < currentHHMM` are shown. Future-window uncompleted blocks aren't decided yet (still active).
- **Future day** → never shown (analytics_view rejects future dates anyway).

The frontend refreshes `currentHHMM` on a 1-minute interval (matches `Schedule.vue`'s `nowMinutes` cadence) so blocks transition into the list as their windows close. Without this, a block ending at 11:00 would still appear "active" at 11:30 until manual refresh.

## Templates / Rules ownership

- Both `Template` and `Rule` are owned by a `User` (FK). `Template` has a unique `(user, type)` constraint — at most one weekday and one weekend template per user.
- `seed_templates --user <username>` is **required**; there is no fallback to "first superuser". The `0002_user_fk` migration deletes orphan rows; rerun the seed per user post-migration.
- All API queries are scoped by `request.user`. Cross-user PK access returns **404 (not 403)** to avoid id enumeration — same convention as `block_detail`.
- POST/PUT to `/api/templates/` wrap saves in `transaction.atomic()` and catch `IntegrityError` → `409`. Without the catch the unique-constraint failure becomes a 500 and leaves the transaction in a broken state for any follow-up queries.

## Locking an empty child queryset locks nothing

- `SELECT ... FOR UPDATE WHERE parent_id = ?` against a child table acquires zero row locks when the child set is empty. Two concurrent writers both pass the in-lock emptiness check and both insert.
- For "create children only when none exist" flows (currently `ai_generate_draft`), lock the **parent row** instead: `Schedule.objects.select_for_update().get(pk=schedule.pk)` then read the children. The parent lock serialises every potential writer for that parent.
- SQLite silently strips `FOR UPDATE`, so SQL grepping doesn't verify intent — spy on `Manager.select_for_update` in tests instead. PostgreSQL honours the lock at runtime.

## Rate-limit consumption order

- `ai_command` accepts the rate-limit-as-decorator pattern because its only pre-LLM precondition is request shape. For `ai_generate_draft`, common pre-LLM rejections (422 no template, 409 non-empty schedule, 413 oversized body, 400 invalid date) **must not** consume the small (default 10/hr) draft budget — a stale page or a misconfigured account would otherwise exhaust the budget without any LLM call.
- Pattern: drop the decorator, increment the counter inline via `_consume_rate_limit(...)` after every precondition guard and before the LLM call. Provider failures (502/503/504) do still consume the budget — they represent a real LLM call attempt and unlimited retries on a flapping provider would bypass the limit.

## Auto-draft trigger

- `schedule_view` returns two related Inertia props:
  - `auto_draft_pending`: one-shot signal, true only on the request that *created* the `Schedule` row, AND a template exists, AND `LLM_API_KEY` is set.
  - `has_template_for_type`: ongoing capability flag that drives `RegenerateDraftButton`'s enable/disable state. `auto_draft_pending` flips false after the first paint and can't be reused as a capability signal.
- The frontend uses a `watch(...)` on `[date, auto_draft_pending, blocks.length]` with `immediate: true` and a per-component-instance `attemptedAutoDraftDates: Set<string>` to fire `generateDraft` exactly once per `(component instance, date)` pair. Don't move this to `onMounted` — Inertia's partial reloads (used by every mutation) explicitly do not remount, so `onMounted` would miss new dates reached via partial reload.

## Inertia partial reload props

- Every mutation now needs `router.reload({ only: ["blocks", "schedule"] })`. Reloading only `blocks` would leave `schedule.status` stale and the badge / regenerate button out of sync. Affected files: `useAI.ts`, `useSchedule.ts` (which `useUndo` and `useDrag` go through), `useDraft.ts`.
- `auto_draft_pending` is its own Inertia prop, NOT part of `schedule`. Partial reloads of `["blocks", "schedule"]` do not refresh it. The frontend keeps its own `attemptedAutoDraftDates` set per component instance to prevent refire.

## PR review iteration loop (AI-driven changes)

For PRs the AI assistant authors in this repo, run the full review-iterate loop autonomously, then **stop at the merge boundary**.

### The loop

1. Open the PR (push branch + `gh pr create`).
2. Wait for `claude-review` (and any other CI) to land. Use the Monitor tool to be notified — don't poll, don't sleep.
3. Read review comments end-to-end before reacting.
4. Triage every finding by **severity AND validity** — not just severity:
   - **Real P0 / P1** (genuine bugs, missed test gaps, real security holes) → fix.
   - **False-positive P0 / P1** (see patterns below) → reject in writing on the PR (a short comment explaining the rationale) rather than silently ignoring. Do not change code to satisfy a misclassified finding.
   - **P2 / P3** → apply the cheap ones inline; otherwise add to `tasks/todo.md` "Follow-ups" section.
5. Push the fixes as one or more follow-up commits. Force-push only when amending the still-pending top commit on a one-commit PR; otherwise stack.
6. Loop back to step 2 until either no findings remain or only P2/P3 are left.

### The merge step is NOT in the loop

When the loop terminates, **report status** (passing CI, no/only-low findings) and **wait for an explicit `merge` / `ok merge` / equivalent from the user** before running `gh pr merge`. Phrases like "fix it", "address the review", "apply suggestions" authorize the code changes only — not the merge. The user retains the merge decision regardless of how confident the automation, the CI, or the auto-reviewer is. Longer-form rationale: `~/.claude/projects/-Users-erzhan-DATA-PROJ-day-forge/memory/feedback_pr_merge.md`.

### Reviewer false-positive patterns observed (don't auto-comply)

These have shown up repeatedly from `claude-review` and were rejected with the user's agreement; recognise the pattern and push back instead of complying:

- **Demanding env vars for credentials in local-dev test fixtures** whose password is clearly marked `do-not-use-in-prod` and whose target is `localhost`. The "credentials" are a fixture, not real secrets; env-var indirection adds friction without changing the threat model.
- **Asking for runtime "production-detection" guards** (e.g. "refuse to run if DB > 50MB") that don't model the actual threat — a dev script's reach is constrained by network / Django settings, not by file sizes. The threshold is also arbitrary and false-positives on real dev DBs after enough use.
- **Suggesting `createsuperuser` (interactive) replace an idempotent Django shell snippet** on "security" grounds. The interactive command breaks automation; the snippet's idempotency IS the point.
- **Adding `refresh_from_db()` after `select_for_update().get()`** "for safety". The `SELECT ... FOR UPDATE` IS the synchronization point — there is no fresher state to fetch.
- **Adding indexes that already exist by Django default** (e.g. on a `OneToOneField`'s implicit unique index, or an `UniqueConstraint(fields=['a', 'b'])`'s composite index). Verify with `sqlite_master` / `pg_indexes` before agreeing.

When in doubt: **a written rejection on the PR > silent ignoring > complying with bad advice**. The conversation log of "here's why we rejected this" is itself useful context for the next reviewer pass.

## New authenticated Inertia page checklist (feature 0010)

Any new authenticated Inertia page MUST do both of:

1. **Backend**: the view passes `ui_preferences={"theme": prefs.theme}` in its Inertia props AND `template_data={"initial_theme": prefs.theme}` to `inertia_render`. Resolve `prefs` exactly once per request via `templates_mgr.preferences.get_user_preferences(request.user)`. Without `template_data`, `base.html` falls back to the `'classic'` default and Strategic users see a Classic-light flash on the first paint.
2. **Frontend**: the page component calls `useThemeFromProps()` (`frontend/src/composables/useThemeFromProps.ts`) once in its `setup()` block. Without it, partial Inertia reloads that include `ui_preferences` do not propagate to `<html data-theme>`.

### Concrete wiring example

```python
# backend/<app>/views.py
from inertia import render as inertia_render
from templates_mgr.preferences import get_user_preferences

@login_required
def my_new_page_view(request):
    # Resolve once — both the prop and the SSR template_data use the same value.
    prefs = get_user_preferences(request.user)
    return inertia_render(
        request,
        "MyNewPage",
        {
            # ...your page's own props...
            "ui_preferences": {"theme": prefs.theme},
        },
        template_data={"initial_theme": prefs.theme},
    )
```

```vue
<!-- frontend/src/pages/MyNewPage.vue -->
<script setup lang="ts">
import { useThemeFromProps } from "../composables/useThemeFromProps"
import "../app.css"

// One line, in setup(). Without this, the SSR data-theme is correct on
// first paint but won't follow user theme changes via partial reload.
useThemeFromProps()
// ...rest of your script setup...
</script>
```

If the page renders TimeBlock / SkippedTasks / CategoryBreakdown (or any future component that needs `getCategoryColor()`), also import `useActiveTheme()` from `../composables/useActiveTheme` and pass its computed value into `getCategoryColor(category, activeTheme)`. The category color resolver is non-reactive otherwise.

The P7 SSR first-paint test and the static-scan test enforce (1) and (2) at CI; the rule is documented here so the convention survives session boundaries.

## CalDAV / Apple Calendar (feature 0011)

### Service-boundary owns the secret
`backend/calendar_sync/service.py:fetch_events_for_date` is the **only**
function that calls `account.get_password()`. Views pass the
`CalDAVAccount` instance through; they never touch the plaintext. If a
new code path needs the password, add it inside `service.py` rather than
in the view, otherwise the "credentials never logged" regression test
(`test_calendar_sync_service.py::TestCredentialsNeverLogged`) becomes a
liar.

### Versioned cache keys + the `auto_now` footgun
`backend/calendar_sync/cache.py` keys events by
`account.updated_at.isoformat()` (microsecond precision). Any mutating
call site **must** either call plain `account.save()` (no `update_fields`)
or include `"updated_at"` in the `update_fields` list — a partial save
that omits it bypasses `auto_now=True` and the cache version doesn't
rotate, serving stale events to every worker. The docstring on
`CalDAVAccount.set_password` calls this out at review time;
`test_cache_invalidates_on_account_update` catches the runtime symptom.

### `event.icalendar_instance` is the pinned parse accessor
The Phase 0 spike (`backend/tests/test_caldav_parse_spike.py`) pinned
`event.icalendar_instance` (returns an `icalendar.Calendar`) as the
canonical accessor for `recurring_ical_events.of(...).between(start, end)`.
Don't switch to `icalendar.Calendar.from_ical(event.data)` — it re-parses
on every call and duplicates the work the lib already did.

### `requestJson` cancellation contract
`frontend/src/composables/useHttp.ts:requestJson` accepts an optional
fourth `{ signal }` arg. `AbortError` propagates as a thrown rejection
(unlike normal network failures, which map to `{ok: false, errors: {...}}`).
Stale-response-guard consumers (`useCalendar`, `useCalendarAccount`)
catch and swallow `AbortError` so the superseded op doesn't flip their
`loading` / `error` state. GET-call shape footgun: pass `undefined` as
the third positional arg — `requestJson(url, "GET", { signal })` would
serialise the options object as the JSON body.

### Stale-response guard requires BOTH date and seq tokens
`useCalendar.fetchEvents` uses two commit tokens
(`latestRequestedEventDate` + `eventsRequestSeq`) — date alone is
insufficient because two fetches for the same date can interleave (retry,
`onMounted` + `watch` double-trigger). `useCalendarAccount` splits reads
and writes onto separate seqs and adds `writeCompletionTick` so a read
can never supersede a write. See `useCalendarAccount.ts` header comment
for the full design and the scenario that motivates each guard.
