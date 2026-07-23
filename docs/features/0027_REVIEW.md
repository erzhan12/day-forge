# Feature 0027 — Code Review

Feature: preserve Habitica app task order in the Day Forge sidebar (dailies
first, then todos, each in the pre-sorted `GET /api/v3/tasks/user?type=` array
order instead of re-sorting by `due_date`/`title`/`id`).

## External review trail

**Engines:** codex (OpenAI) + cursor (agent), read-only, run against
`git diff HEAD` in the `feature/0027-habitica-sidebar-order` worktree.

**Rounds:** 1 (both engines returned `NO P1/P2 FINDINGS` on the first pass).

**Findings:** raised 5 (all P3), accepted 1 (fixed), P3-noted 4.

### Fixed (P3, both engines converged)

- New order tests (`test_fetch_preserves_api_array_order_within_type`,
  `test_fetch_filtered_subset_preserves_relative_api_order`) did not assert the
  outgoing `requests.get` `params` the way sibling tests do
  (`test_fetch_filters_todos_and_due_dailies_for_client_today:72`). Added
  `params == {"type": "todos"}` / `{"type": "dailys"}` assertions so a
  regression that requests the wrong Habitica task type — while still consuming
  the mocked responses in order — is caught.

### Noted, not actioned (P3, non-blocking)

- Filtered-subset test asserts `id` order only, not `t.position == 1/3`. Order
  coverage is the behaviour under test; position values are an internal
  implementation detail. Left as-is.
- `test_fetch_position_tiebreaks_on_id` omitted — plan §4 explicitly allows
  skipping it because `enumerate` makes equal positions within a type
  impossible. Not a real gap.

## Plan conformance (verified against code)

- `NormalizedHabiticaTask` gains internal `position: int = 0`; **not** added to
  `normalized_task_to_dict` → JSON response shape unchanged.
- `_normalize_todo` / `_normalize_daily` take keyword-only `position`; fetch
  loops pass `enumerate` index **before** filtering, preserving relative API
  order among included tasks.
- Sort key changed to `(-int(type == "daily"), position, id)`; `due_date` and
  `title` removed.
- No `raw.get("position")` read anywhere — the field is absent in live payloads.
- Existing client-today test expectation flipped from `[daily-due, overdue,
  today, undated]` to `[daily-due, today, overdue, undated]` to match array
  order (documented in plan §Current-state and §4).

## Verification

- `uv run pytest backend/tests/test_habitica_sync_service.py backend/tests/test_habitica_sync_views.py -q` → **27 passed**.
- `uv run ruff check backend/habitica_sync/ backend/tests/test_habitica_sync_service.py` → **All checks passed**.

**Result: SUCCESS — zero valid P1/P2, tests + lint green.**
