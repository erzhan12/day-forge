# 0101 — task_id hardening tasks

- [x] Add failing tests for malformed ids (400, no upstream call), empty/slash routing 404, validator unit cases, service percent-encoding, and service rejection of `.`/`..`
- [x] Add `is_valid_task_id` in Todoist and Habitica `schemas.py`
- [x] Validate in both complete views before the account 503; return `_envelope("Invalid task id.", 400)`
- [x] Percent-encode `task_id` in both `complete_task` implementations; reject exact `.` and `..`
- [x] Comment in `urls.py` why the route stays `<str:task_id>`
- [x] Update existing Habitica view tests that posted `task-id` to a canonical UUID
- [x] Update the Todoist `complete_task` docstring
- [x] OpenSpec change (this directory) and archive on the feature branch
- [x] Close the #308 item in `tasks/todo.md`
- [x] Run `make check` and `make frontend-build` (after archive)
