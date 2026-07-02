# Feature 0020 - Code Review: Todoist Integration (read-only task panel)

**Reviewed:** working tree vs `docs/features/0020_PLAN.md`  
**Review date:** 2026-06-19  
**Verification:**

- `uv run pytest backend/tests/test_todoist_sync_*.py -q` - 73 passed
- `npm test -- --run useTodoist TodoistTasksPanel useTodoistAccount` - 29 passed
- `uv run ruff check backend/` - passed
- `cd frontend && npx vue-tsc --noEmit` - passed

## Findings

No blocking correctness findings.

The previous Todoist status-handling pitfall is covered: `useTodoist.ts`
only elevates `connected = true` on task-fetch failures when
`result.status !== undefined`, so no-status network failures no longer
prove account existence by accident. The regression is covered by
`frontend/tests/useTodoist.test.ts`.

## Non-blocking Follow-ups

### 1. Phase 0 live filter spike is still absent

**Plan ref:** `0020_PLAN.md` Phase 0

`backend/tests/test_todoist_filter_spike.py` and
`docs/features/0020_spike.md` do not exist. The unit tests pin the
generated query strings (`today | overdue` and bare `YYYY-MM-DD`), but
they do not validate Todoist's live interpretation of those filters.
This was listed as recommended, not required, and should be gated behind
an env-provided token if added.

### 2. `useTodoist.fetchAccountStatus` still ignores non-OK responses

**File:** `frontend/src/composables/useTodoist.ts`

The schedule page also calls `fetchTasks` immediately, so user-visible
task errors are handled there. This matches the local CalDAV pattern, but
it leaves standalone status-fetch failures silent.

### 3. No service-layer decryption propagation test

The view test covers `ImproperlyConfigured` by mocking
`fetch_tasks_for_date`, but there is no service test proving
`account.get_token()` decryption failures propagate as
`ImproperlyConfigured` instead of being wrapped as `TodoistProviderError`.
The current implementation does propagate correctly because decryption
happens before the broad `try` block.

## Plan Compliance

Backend implementation matches the plan:

- `todoist_sync` app, migration, settings, URLs, admin, checks, crypto,
  model, cache, schemas, service, and views are present.
- `TODOIST_BASE_URL` defaults to `https://api.todoist.com/api/v1`.
- Fetch uses `/tasks/filter` with `query`, `limit=200`, cursor
  pagination, `today | overdue` only for project-local today, and bare
  literal dates otherwise.
- Task normalization maps raw `content` to wire `title`, drops timed due
  values to date-only, keeps `due_date` nullable, emits raw `priority`
  plus `ui_priority`, and sorts with a null-safe deterministic key.
- Account status never returns token-shaped fields; task payload is
  snake_case and matches `frontend/src/types/todoist.ts`.
- Service errors map to 401/502/504, missing account maps to 503, and
  decryption/config failures map to the pinned 500 message.

Frontend implementation matches the plan:

- `useTodoistAccount`, `useTodoist`, `TodoistTasksPanel`, Schedule wiring,
  Settings wiring, and Todoist types are present.
- GET calls use `requestJson(url, "GET", undefined, { signal })`.
- `fetchTasks` uses date + sequence commit guards; abort/stale paths do
  not mutate `connected` or `statusKnown`.
- Panel copy, `aria-label`, empty state, CSS prefix, and P1-P4 priority
  dots match the plan; no project chip, due time, link-out, edits, or AI
  coupling are present.

Docs match the plan:

- `.claude/rules/project.md` documents `TODOIST_*`, token rotation, shared
  cache, and no AI provider egress.
- `RULES.md` contains the Todoist service boundary, cache, filter, GET
  request shape, and status-gating notes.
- `docs/api.md` documents the Todoist account and task endpoints.

## Test Review

Backend tests cover service success and typed errors, filter selection,
pagination, priority mapping, due normalization including timed suffixes,
null-safe sort, malformed-task skipping, token logging, views, cache
versioning, CSRF/auth guards, and system checks.

Frontend tests cover request argument shape, stale response guards,
503/non-503/no-status connected-state behavior, abort behavior, account
operation serialization, read/write commit guards, panel states, copy,
priority rendering, and absence of out-of-scope UI.
