# Feature 0021 Code Review

## Findings

No blocking or functional findings.

The implementation matches `docs/features/0021_PLAN.md` for the new Todoist complete endpoint, cache invalidation, manual refresh cache bypass, frontend optimistic removal/rollback, refresh event wiring, and the explicit deferral of polling.

## Notes

- Minor documentation drift: `backend/todoist_sync/cache.py:1` and `backend/todoist_sync/cache.py:3` still describe the cache as per-`(user, date)` and show the key shape without the `filter_scope` suffix, while `tasks_cache_key()` includes `filter_scope` at `backend/todoist_sync/cache.py:48`. This is not a behavior bug, but future readers may miss that `exact` and `with_overdue` are isolated cache entries.

## Test Coverage Reviewed

- Backend service tests cover `complete_task` success (`204`/`200`), alphanumeric ids, `401`/`403`, timeout, provider failures, key-rotation propagation, token-boundary behavior, and no-token-in-logs for the POST path.
- Backend view tests cover view-level delegation, real service-to-POST shape, cache invalidation after complete, no-account `503`, service error envelopes, config `500`, CSRF, anonymous access, method guard, refresh cache bypass/rewarm, and `carry_overdue=1&refresh=1`.
- Frontend composable tests cover optimistic complete success, rollback for HTTP and no-status failures, connection state preservation, concurrent refresh races on success/failure, refresh URL query construction, stale commit guard reuse, and silent refresh/no skeleton flash.
- Component tests cover complete control rendering/emission, sidebar refresh visibility/emission, and complete event passthrough.

## Verification

- `uv run pytest backend/tests/test_todoist_sync_service.py backend/tests/test_todoist_sync_views.py -q` - passed (`90 passed`)
- `cd frontend && npm test -- --run useTodoist.test.ts TodoistTasksPanel.test.ts TodoistSidebar.test.ts` - passed (`43 passed`)
- `cd frontend && npx vue-tsc --noEmit` - passed
- `uv run ruff check backend/` - passed
- `cd frontend && npm run build` - passed
