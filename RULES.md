# RULES.md

Project-specific patterns, pitfalls, and conventions discovered during development.
This is a living document — update it as new patterns emerge.

## Secrets & Environment Files

- Never commit `.env` files. `.gitignore` excludes `.env` and `.env.*`, with `!.env.example` carved out so a sanitized template can be committed.
- Secrets belong in env vars, not code or fixtures. See `backend/day_forge/settings.py` and the env var list in `CLAUDE.md` (`LLM_API_KEY`, `DJANGO_SECRET_KEY`, etc.).
- Before committing, sanity-check with `git ls-files | grep -E '(^|/)\.env'` — should return nothing except `.env.example` if one exists.
- User commands sent to `POST /api/ai/schedules/<date>/command/` are logged verbatim to `AIInteraction` (capped at 2 KB). Treat this table as sensitive; don't paste real secrets into the command bar while testing.

## XSS / Output Escaping

- Block titles flow user → DB → Vue. Vue's `{{ ... }}` text interpolation auto-escapes, and there is **no `v-html` usage** in `frontend/src/`. Do **not** call `django.utils.html.escape()` on titles before saving — Vue would then render `&lt;` literally, mangling legitimate inputs containing `<`, `>`, or `&`. Escape at the render boundary, not the storage boundary, and only if `v-html` is ever introduced.
- LLM-supplied strings are shape/length-validated in `backend/ai/schemas.py`. Control chars below 0x20 (excluding `\t\n\r`) are rejected to keep titles safe for downstream CSV exports and log scrapers.

## AI Undo Registration

- A `200 OK` from the AI command endpoint does **not** always mean the schedule changed. The LLM may return `actions: []` with an explanation (e.g. "outside working hours") — this is a successful interaction with zero mutations.
- Undo must be registered only when `result.data.blocks` actually differs from the pre-submit snapshot. The comparison lives in `_scheduleChanged()` in `frontend/src/components/CommandBar.vue`.
- When `data.blocks` is missing from the response, treat as no change (do not push undo) — this is the safe default.

## Schedule.status flip rules

- `Schedule.status` flips `draft → active` on the **first user mutation** via every forward-mutating endpoint: `create_block`, `block_detail` PATCH, `block_detail` DELETE, `reorder_blocks`, and `ai_command` (only when `len(parsed_actions) > 0`). The helper is `Schedule.mark_active_if_draft()` in `backend/schedules/models.py`.
- `restore_blocks` (the undo target) does **not** flip status. Calling it with the previous block list shouldn't pretend the user just made a fresh edit. Concretely: undoing a freshly auto-generated draft (`restore_blocks([])`) leaves `status="draft"`, so the regenerate button reappears.
- `ai_generate_draft` does **not** flip status. The badge stays "Draft" until the user actually edits.
- `ai_command` returning `actions: []` is a successful no-op (RULES.md / undo gating already documented this). Status flipping must follow the same gate, otherwise an LLM responding with "I don't understand" silently promotes a draft to active.

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
