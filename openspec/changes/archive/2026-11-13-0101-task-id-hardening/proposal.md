# 0101 — Harden task_id on Todoist and Habitica complete endpoints

## Why

`POST /api/todoist/tasks/<task_id>/complete/` and `POST /api/habitica/tasks/<task_id>/complete/` put `task_id` into the upstream URL with no format check and no percent-encoding. A malformed id can change which provider path is called. Impact is low (authenticated, CSRF-protected, POST-only, fixed host, the user's own token). This is defence in depth; see issue #308 and [docs/features/0101_PLAN.md](../../../../docs/features/0101_PLAN.md).

## What changes

- Validate `task_id` at the complete views and return 400 `{"errors": {"detail": "Invalid task id."}}` without an upstream call (including when the user has no account). Todoist ids must match `^[A-Za-z0-9_-]{1,64}$`; Habitica ids must be a canonical hyphenated UUID.
- Keep the `<str:task_id>` route so malformed ids that can be a path segment reach the view (a stricter route would 404). Empty segments and decoded slashes still 404 at routing, with no provider call.
- Percent-encode the id in each `complete_task` with `urllib.parse.quote(task_id, safe="")`. Reject exact `.` and `..` in the service so a direct caller cannot rely on `requests` normalising the path.

## Capabilities

- `integrations/todoist`: ADDED complete-task id format; MODIFIED "Complete a task" (drop "opaque"; 503 only for a valid id).
- `integrations/habitica`: ADDED complete-task id format; MODIFIED "Complete a task" (503 only for a valid id).

## Impact

Complete endpoints only. Existing Habitica view tests that used the non-UUID `task-id` now use a canonical UUID. `docs/api.md` is unchanged in this pass (not approved) and is a documentation follow-up.
