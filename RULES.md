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
- `UndoAction.silent?: boolean` (issue #54) controls **only** the toast, not the stack. `pushUndo` gates `showToast` behind `!action.silent` but always pushes — so Cmd+Z still works for silent actions. Obvious edits (manual add/edit/toggle/delete/drag, AI chat apply in `useChat.ts`) pass `silent: true`; generate-draft in `Schedule.vue` still shows a toast. `performUndo`'s own toasts ("Undone: …", errors, "Nothing to undo.") call `showToast` directly, never `pushUndo`, so they are independent of `silent`.

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

## Active Rules injection across all three AI endpoints

- The command bar (`POST /api/ai/schedules/<date>/command/`), chat (`POST /api/ai/schedules/<date>/chat/`), and draft generator (`POST /api/ai/schedules/<date>/generate-draft/`) all inject the user's active Rules into their server-built prompt context so the model can fill omitted defaults (duration, gap, start time) instead of asking a clarifying question.
- Active/user-owned filtering stays at the **view/query layer**, in the shared `ai.views._load_active_rules(user)` helper. Prompt builders (`build_user_message`, `build_chat_user_message`, `build_draft_user_message`) just render whatever rules they're handed via the shared `_format_rules_section` formatter — they do not query the DB and do not re-filter. Drift between the three endpoints means a bug in one of them, not in the prompt layer.
- Caller orders rules by `-priority` before passing them in; the formatter preserves caller order, so a future "filter inactive at the prompt layer" refactor would silently break the priority-desc invariant.
- Chat-specific: rules render into the **trusted** schedule-context message (the first user-role message), not the untrusted prior-transcript flatten. A tampered client must not be able to impersonate or shadow the user's defaults — see `backend/ai/service.py:run_chat`.

## Locking an empty child queryset locks nothing

- `SELECT ... FOR UPDATE WHERE parent_id = ?` against a child table acquires zero row locks when the child set is empty. Two concurrent writers both pass the in-lock emptiness check and both insert.
- For "create children only when none exist" flows (currently `ai_generate_draft`), lock the **parent row** instead: `Schedule.objects.select_for_update().get(pk=schedule.pk)` then read the children. The parent lock serialises every potential writer for that parent.
- SQLite silently strips `FOR UPDATE`, so SQL grepping doesn't verify intent — spy on `Manager.select_for_update` in tests instead. PostgreSQL honours the lock at runtime.

## Rate-limit consumption order

- `ai_command` accepts the rate-limit-as-decorator pattern because its only pre-LLM precondition is request shape. For `ai_generate_draft`, common pre-LLM rejections (422 no template, 409 non-empty schedule, 413 oversized body, 400 invalid date) **must not** consume the small (default 10/hr) draft budget — a stale page or a misconfigured account would otherwise exhaust the budget without any LLM call.
- Pattern: drop the decorator, increment the counter inline via `_consume_rate_limit(...)` after every precondition guard and before the LLM call. Provider failures (502/503/504) do still consume the budget — they represent a real LLM call attempt and unlimited retries on a flapping provider would bypass the limit.

## Rate-limit increment: sync `cache.incr`, not async `aincr` (feature 0015)

- `_consume_rate_limit` increments via `await sync_to_async(cache.incr, thread_sensitive=True)(key)`, **not** `await cache.aincr(key)`. Django's `RedisCache` overrides only the *sync* `incr` (→ atomic Redis `INCR`); the async `aincr` it inherits from `BaseCache` is a non-atomic `aget`→`aset` read-modify-write that **also** rewrites the key TTL to `default_timeout` (300s), silently collapsing the intended 3600s window. The pattern mirrors how `BaseCache.aadd` itself bridges to the sync `add`. `RedisCache.incr` raises `ValueError` on a missing key, so the `except ValueError → aset` reseed branch survives. Guarded by `test_increment_preserves_window_ttl`.
- The counter must live in a shared, atomic backend. `ai.E001` (`backend/ai/checks.py`) blocks startup when `LLM_API_KEY` is set and `CACHES['default']` is LocMem / FileBased / Dummy — set `REDIS_URL` (→ `RedisCache`) whenever AI is enabled. FileBased is rejected because its `incr` is not atomic across workers (file locks ≠ Redis `INCR`), not because it is per-process (only LocMem / Dummy are per-process).

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

## Google Calendar / OAuth (feature 0022)

`backend/gcal_sync/` mirrors the `calendar_sync` skeleton (crypto / models /
service / cache / checks / views) but for OAuth, multi-account, and an async
events path. Key divergences and footguns:

### Multi-row account model + upsert
`GoogleCalendarAccount` is **`ForeignKey`** (multi-row per user), not the
`OneToOne` of CalDAV/Todoist, with `UniqueConstraint(user,
google_account_id)`. The callback upserts via
`get_or_create(user=…, google_account_id=…)` under
`select_for_update()`, so reconnecting the same Google account **updates** the
row (idempotent). Cache keys therefore embed `account.id` (a user has many
accounts) — `gcal_events:{user_id}:{account_id}:{updated_at}:{date}`.

### Partial success — never blank the panel
The events view (`async def`) fans out with
`asyncio.gather(..., return_exceptions=True)`; a single account's
`GoogleCalAuthError` becomes an `account_errors[]` entry
(`reconnect_required`) while healthy accounts' events still return (HTTP 200).
Only `ImproperlyConfigured` (key rotation, server-wide) short-circuits to a
config-500. The response is the composite `{"events": [...], "account_errors":
[...]}` (the latter always present). The frontend mirrors this: provider
errors are **non-suppressing banners**, never the single suppressing `error`
prop that `ExternalEventsPanel` used pre-0022 — a Google failure must not blank
healthy Apple events. Per-provider retry is routed separately
(`retry(provider)`), Apple ≠ Google.

**Panel placement (wide-only):** `ExternalEventsPanel` lives inside the left
`TodoistSidebar` (default slot, stacked under the Todoist list) — **not** the
main column. Users can switch back to the legacy center-column placement in
**Settings → External Calendars → Event panel placement** (`externalCalendarPlacementStorage.ts`, device-local). The sidebar shows on wide viewports (`isWide`) when **either**
Todoist or a calendar is connected (`Schedule.vue:leftSidebarVisible`), with
`showTasks` / `showExtra` gating each section. Center placement renders the
panel above `AddBlockForm` on all viewports (legacy behavior). On narrow/mobile
with sidebar placement there is **no** external-calendar panel by design. Note: `useCalendar`/`useGoogleCalendar` still
fetch on every date regardless of viewport, so on narrow the events are fetched
but not displayed — a deliberate simplicity trade-off (gate the fetch on
`isWide` if that egress ever matters).

### Token refresh concurrency (the P1/P2 design)
`_ensure_access_token` (async) is the only refresh-token decrypt site. The
`select_for_update` lock is acquired in the sync `_persist_refreshed_tokens`
**after** the network refresh, NOT held across it (holding a row lock across an
external HTTP call is an anti-pattern — P2). So two callers can both refresh
against Google before either locks; the guarantee under test is
**persisted-token correctness, not call count**. Double-check: a caller that
finds the row already fresh **and** has no rotated refresh token skips the
write; but a caller holding a **rotated** refresh token persists it even when
the access token is fresh (Google may invalidate the old refresh token on
rotation — P1). All persists are full `save()` (no `update_fields`) so
`auto_now` rotates the cache version (same footgun as CalDAV/Todoist).
`_persist_refreshed_tokens` returns `(token, updated_at)` and
`_ensure_access_token` copies the post-refresh `updated_at` back onto the
**in-memory** account — otherwise a refresh-during-request bumps the DB
version while the view's stale `acc` writes the post-fetch cache under the
dead pre-refresh key (next read misses it; perf-only but wasteful).

### Async-safety gotchas
- The events view does `user = await request.auser()` FIRST; touching the sync
  `request.user` proxy in an `async def` body raises `SynchronousOnlyOperation`
  (the 0009 AI-view pattern). Use the `auser()` result everywhere downstream.
- Parse the `<date>` route string to `datetime.date.fromisoformat(date)` and
  pass the **`date` object** (never the raw string) to the cache + service —
  the cache key calls `target_date.isoformat()`.
- `gcal_sync/cache.py` helpers are `async` (`cache.aget`/`aset`) because the
  only caller is the async view; sync `cache.get/set` under `RedisCache` would
  block the event loop. (The `aincr` non-atomic-RMW footgun is rate-limiter
  specific and does NOT apply to these idempotent versioned get/set.)
- The sync refresh transport runs via `asyncio.to_thread`; the sync ORM persist
  via `sync_to_async(..., thread_sensitive=True)`. `_refresh_sync` is
  **pure-network** (no ORM write) so no sync `.save()` is smuggled into a
  worker thread.

### OAuth correctness
- Scopes are **`.split()`** from the space-separated `GOOGLE_OAUTH_SCOPE` and
  requested as **canonical** strings (`…/auth/userinfo.email`, not the `email`
  alias) so the returned scope set matches and oauthlib doesn't raise "Scope
  has changed". `build_authorization_url` does **not** pass
  `include_granted_scopes` (incremental auth would let Google merge a user's
  other grants on the same client into a superset that trips the scope-equality
  check on `fetch_token`); `service.py` also `os.environ.setdefault`s
  `OAUTHLIB_RELAX_TOKEN_SCOPE=1` as belt-and-suspenders.
- Calendar ids are **`urllib.parse.quote(cal_id, safe="")`**-encoded in the
  events path — Google ids routinely contain `@`/`#` (shared
  `…@group.calendar.google.com`); unescaped they break into extra path
  segments and silently fail shared-calendar fetches.
- **PKCE is disabled** (`_build_flow` sets `flow.autogenerate_code_verifier =
  False`). google-auth-oauthlib defaults it True, so `authorization_url` emits
  a `code_challenge` and stashes the `code_verifier` on the Flow instance — but
  we rebuild a fresh, stateless Flow at callback time, so the verifier is gone
  at token exchange → Google `invalid_grant: Missing code verifier`. We're a
  confidential Web client (client_secret), so PKCE is optional. While PKCE
  provides defense-in-depth even for confidential clients (RFC 7636), the
  marginal benefit is outweighed by the session-persistence complexity in this
  stateless Flow-rebuild architecture; the existing protections (client_secret,
  CSRF state, server-controlled redirect_uri, HTTPS) remain robust. If you ever
  want PKCE back, persist the verifier in the session next to `state`. See
  RFC 7636 for the PKCE spec.
- `connect`/`callback`/`accounts` are sync; only `events` is async. The CSRF
  `state` lives in the session and is `pop`ed in the callback (no replay).
- `exchange_code` (sync) uses `httpx.Client`; the events path uses
  `httpx.AsyncClient`. Don't cross them.

### Shared `NormalizedEvent` (cross-app, intentional)
`gcal_sync` imports `NormalizedEvent` / `normalized_event_to_dict` from
`calendar_sync.schemas` — single source of truth, **deliberate**, not a
layering violation. 0022 added a trailing `account_label: str = ""` field (the
default keeps every existing CalDAV positional constructor + test compiling);
Apple leaves it `""`, Google fills the account email. The frontend
`NormalizedEvent` type + the CalDAV/Google API docs all carry the field.

### Prod boot dependency (divergence from CalDAV)
`gcal_sync.E001` blocks `DEBUG=False` startup if **any** of the four
`GOOGLE_OAUTH_*` vars (client id/secret, redirect uri, token key) is
unset/malformed — **even when no user has connected Google**, unlike
`calendar_sync.E001` (encryption key only). A Google-less staging env must set
all four or stay `DEBUG=True`.

### Tests without pytest-asyncio
Async service functions are driven from sync tests via `asyncio.run(...)`. The
account fixture carries a **fresh cached access token** so
`_ensure_access_token` returns early (no refresh, no `sync_to_async` persist,
no cross-thread DB connection). The refresh/rotation guards are tested directly
against the sync `_persist_refreshed_tokens`. The async events view is driven
through Django's test `Client` with `views.service.fetch_events_for_account`
patched.

## Todoist (features 0020, 0021)

`todoist_sync` mirrors `calendar_sync` one-for-one (new app, same error
hierarchy, versioned cache, system checks, admin, frontend composables +
panel). Differences: a single secret (personal API token, not
apple_id+password+base_url), an HTTP REST client (`requests`, not a DAV
library), and a date→filter algorithm. The same four rules apply:

### Service-boundary owns the secret
`backend/todoist_sync/service.py:fetch_tasks_for_date` **and**
`complete_task` (feature 0021) are the **only two** functions that call
`account.get_token()` (each `del token` in a `finally`). Views pass the
`TodoistAccount` instance through; they never touch the plaintext. New
token-using code goes in `service.py`, or the "token never logged"
regression test (`test_todoist_sync_service.py`, locked across both call
sites by `TestTokenBoundary`) becomes a liar.

### Versioned cache keys + the `auto_now` footgun
`backend/todoist_sync/cache.py` keys tasks by
`account.updated_at.isoformat()`. Any mutating call site **must** call
plain `account.save()` (no `update_fields`) or include `"updated_at"` —
a partial save bypasses `auto_now` and serves stale tasks. The
`TodoistAccount.set_token` docstring calls this out. Cache invalidation on
task complete (feature 0021) is **not** key-deletion: `cache.invalidate_tasks(account)`
just does a plain `account.save()` to bump `updated_at` (rotates every
`todoist_tasks:*` key at once, no key enumeration) — so it is governed by
the **same** footgun. Keep it a plain `save()`.

### Date→filter algorithm + nullable `due_date`
`service.py` maps the selected date to a Todoist filter query and hits the
**dedicated filter endpoint** `GET /api/v1/tasks/filter` (required param
`query`; cursor-paginated `{results, next_cursor}`, `limit` max 200 — loop
until `next_cursor` is null). `selected_date == today` → `query =
"today | overdue"`; else the bare literal-date token `query =
"<YYYY-MM-DD>"` (`due:` semantics; **not** the `date:` keyword). Sort
with a **null-safe** key — `due_date` is nullable (`due == null` → `None`),
so use `key=lambda t: (-t.priority, t.due_date or "", t.title.casefold(),
t.id)`; a bare tuple raises `TypeError` the moment a no-due task appears.
Tasks with no due date never match a date-scoped query, so they never
appear in the panel (by design — empty-state copy must not imply zero
tasks). The `due.date` field is **polymorphic** (full-day `"YYYY-MM-DD"`
vs. timed `"...T..."`); normalise via the `"T"`-in-`raw` branch, time
component dropped. The wire field for the task name is `title` (never
`content`).

### `requestJson` GET footgun + dual-token stale guard (frontend)
Same as CalDAV: `useTodoist.fetchTasks` passes `undefined` as the 3rd
positional arg and `{ signal }` as the 4th; it guards with two commit
tokens (`latestRequestedTaskDate` + `tasksRequestSeq`).
**Connected-state divergence from `useCalendar`**: `GET
/api/todoist/tasks/<date>/` returns `503` **only** on
`TodoistAccount.DoesNotExist`, so a non-503 error (401/500/502/504)
*proves* the account exists — `fetchTasks` sets `connected = true` on
those (not just `503`/`ok`), so the panel's `!connected` gate doesn't hide
the error on first load before `fetchAccountStatus()` resolves.

### Two-way sync (feature 0021): complete + live refresh
- **Optimistic complete with *surgical* rollback** —
  `useTodoist.completeTask` captures **only** the removed task + its index
  (`idx`/`removed`), **never** a whole-list snapshot. On failure it
  re-inserts only that task into the **current** list (and only if absent);
  on success it idempotently re-filters the current list. A whole-list
  `state.tasks = previous` restore would clobber a concurrent `refreshTasks`
  commit (e.g. complete A from `[A,B]`, refresh commits `[B,C]`, A fails →
  a whole-list restore drops C and resurrects A). Always operate on the
  *current* `state.tasks` at success/failure time, not a call-time snapshot.
- **`refresh=1` cache-bypass** — `GET /api/todoist/tasks/<date>/?refresh=1`
  skips the read cache but still re-warms it (additive; no regression to the
  cached read-only flow). `carry_overdue` and `refresh` are independent
  query flags.
- **Silent refresh (no skeleton flash)** — `fetchTasks` delegates to an
  internal `_fetchTasks(date, { force, silent })`. `refreshTasks` passes
  `{ force: true, silent: true }`: `silent` **skips** the `loading=true`
  flip so existing rows stay visible (the panel renders the skeleton on
  `loading`). The initial `fetchTasks` keeps `silent: false`. If you add a
  new fetch entry point, decide `silent` deliberately — a stray
  `loading=true` on a background refresh regresses the no-flash UX.
- **Background polling (#71)** — `TODOIST_POLL_INTERVAL_SECONDS` (default
  `0`) is passed to Schedule as `todoist_poll_interval`. When `> 0` and
  the Todoist sidebar is open on a wide viewport with a connected account,
  `useTodoistPoll` calls `refreshTasks` on that interval (`?refresh=1`,
  silent). Polling pauses while `document.hidden`; one refresh fires when
  the tab becomes visible again. Collapsing the sidebar or disconnecting
  Todoist clears the interval.
- **Complete view parses no body** — `POST .../complete/` takes the id in
  the URL path and reads **no** `request.body`, so it has **no**
  `reject_oversized_body` guard (unlike `POST /account/`). Precedence is
  just `503` (no account) → `2xx`/service-error.

## External tasks panel (issue #73 — planned)

**UX decision:** one **left-side panel** on Schedule, grouped by integration
(Todoist, Habitica, future apps) — not a separate sidebar per provider.
Today's `TodoistSidebar.vue` (feature 0020) will be refactored into a shell
(`ExternalTasksSidebar.vue`) with per-source **sections**
(`TodoistTasksSection`, `HabiticaTasksSection`, …). Each integration keeps
its own backend app (`*_sync`) and composable (`useTodoist`, `useHabitica`);
the shell owns collapse/expand, width, and global refresh. Panel shows when
**any** connected source is present. New integrations add a section +
composable only — no duplicate sidebar chrome.

**Polling decision (#73):** one shared **`EXTERNAL_TASKS_POLL_INTERVAL_SECONDS`**
(default **`10`**, `0` = off) for the whole panel — replaces
`TODOIST_POLL_INTERVAL_SECONDS` / `useTodoistPoll` when the panel refactor
lands. While the panel is open on a wide viewport with ≥1 connected source,
`useExternalTasksPoll` silently calls `refreshTasks` on every connected
composable every 10s (`?refresh=1`); pauses when `document.hidden`.

## Production deploy (feature 0016)

The production deploy lives in `deployment/` and targets
`dayforge.habitreward.org` behind the shared habit_reward Caddy. See
`deployment/README.md` for the one-time manual ops checklist.

- **`SECURE_PROXY_SSL_HEADER` is mandatory behind Caddy.** TLS terminates
  at the proxy; the app gets plain HTTP. Without
  `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
  (settings.py, `if not DEBUG`), `SECURE_SSL_REDIRECT` sees every request
  as insecure and `DEBUG=0` 301-**infinite-loops**.
- **Health probes to `http://localhost:8006/...` need two headers** under
  `DEBUG=0`: `X-Forwarded-Proto: https` (or `SECURE_SSL_REDIRECT` 301s it)
  **and** `Host: dayforge.habitreward.org` (or `ALLOWED_HOSTS` rejects
  `localhost` with 400). The Dockerfile + compose healthchecks send both;
  the pre-flight uses `ALLOWED_HOSTS=localhost` so only the proto header.
- **Two stacks.** Prod is the `deployment/` stack (multi-stage Dockerfile,
  uvicorn ASGI `--workers 1`, `DEBUG=0`). The root `Dockerfile` /
  `docker-compose.yml` stay **dev-only** (`runserver`, `DEBUG=1`, mounts).
- **Static path chain:** Vite `frontend/dist` → `STATICFILES_DIRS` →
  `collectstatic` → WhiteNoise serves it (no Caddy `file_server`).
- **SQLite** lives at `/app/db/day_forge.db`; bind-mount `./data:/app/db`,
  host dir owned by **uid 1000** (the container's `app` user).
- **`:8006` must be locked down via DOCKER-USER iptables** — `ufw deny`
  alone does not block Docker-published ports. Allow Docker-private
  **source** CIDRs (`172.16.0.0/12`), not `-i docker0` (Caddy uses Compose
  `br-*` bridges). Caddy reaches the app via `host.docker.internal:8006`
  on the bridge — do **not** switch to a `127.0.0.1:8006` bind.
- **First deploy:** wire the central Caddy block before expecting the CI
  HTTPS health-check to pass (it probes Caddy, not the app port).

## Sound notifications (feature 0019, issue #56)

Opt-in chime at block start/end. Frontend-only; `useSoundNotifications.ts`
piggybacks the existing 60s `useNowMinutes` sampler — **never add a second
interval** (it would drift out of phase with the now-line). Setting persists
in localStorage (`soundNotificationStorage.ts`, strict-only-on-**true** so
the safe failure mode is silence — inverse of `chatSidebarStorage`).

- **Time-trigger dedup keys MUST include the time, not just the entity id.**
  The fired-Set keys `start:${block.id}:${date}:${minutes}`. A re-timed block
  keeps its `id` across the `router.reload({only:["blocks","schedule"]})`
  re-flow, so an id-only key would suppress the new boundary's chime after
  the old one fired. Any future "fire once per X" guard over re-flowable
  rows has the same footgun.
- **The `AudioContext` is a module-level singleton (`utils/audioContext.ts`)
  that is never closed.** It must survive the Settings→Schedule Inertia
  navigation: the opt-in toggle click is the autoplay-unlock gesture, and it
  has to unlock the *same* context the Schedule detector later plays through.
  A per-instance or refcount-to-0-close context would re-suspend on every
  navigation and drop the first chime. Do **not** close it on component
  unmount.
- **Detection is crossed-since-last-sample `(prev, now]`, not exact equality**
  — a background-tab tick is throttled/coalesced and can skip the exact
  boundary minute. First tick of a date fires exact-`now` only (no
  back-fill); a backward clock step (DST / manual) fires nothing.
- **Inherited limitation:** a tab left open across midnight stops firing
  until date navigation, because `useNowMinutes.tick()` calls `leaveToday()`
  (clears the interval, `nowDate=null`) and never re-arms. Not fixable
  without the forbidden second timer.
