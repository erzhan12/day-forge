## ADDED Requirements

### Requirement: Complete-task id format
The system SHALL reject a `task_id` that does not match `^[A-Za-z0-9_-]{1,64}$` on `POST /api/todoist/tasks/<task_id>/complete/` with 400 `{"errors": {"detail": "Invalid task id."}}` and MUST NOT call Todoist, including when the user has no account. The service SHALL percent-encode the id and reject exact `.` and `..`.
Enforced: backend/todoist_sync/schemas.py::is_valid_task_id, backend/todoist_sync/views.py::complete, backend/todoist_sync/service.py::complete_task

#### Scenario: Malformed id
- **WHEN** a connected user POSTs a complete path whose decoded `task_id` is not `^[A-Za-z0-9_-]{1,64}$`
- **THEN** the response is 400 `{"errors": {"detail": "Invalid task id."}}` and Todoist is not contacted

Tests: backend/tests/test_todoist_sync_views.py::TestCompleteView::test_malformed_task_id_returns_400_without_upstream, backend/tests/test_todoist_sync_views.py::TestCompleteView::test_twice_encoded_slash_returns_400, backend/tests/test_todoist_sync_views.py::TestTodoistTaskIdValidation::test_invalid_ids_are_rejected

#### Scenario: Malformed id without an account
- **WHEN** a user with no Todoist account POSTs a malformed `task_id`
- **THEN** the response is 400 with the same envelope, not 503, and Todoist is not contacted

Tests: backend/tests/test_todoist_sync_views.py::TestCompleteView::test_malformed_task_id_returns_400_without_account

#### Scenario: Id rejected at routing
- **WHEN** the path has an empty `task_id` segment or a decoded slash
- **THEN** the response is 404 and Todoist is not contacted

Tests: backend/tests/test_todoist_sync_views.py::TestCompleteView::test_empty_task_id_does_not_match_route, backend/tests/test_todoist_sync_views.py::TestCompleteView::test_decoded_slash_does_not_match_route

#### Scenario: Service encodes and guards path segments
- **WHEN** `complete_task` is called with an unexpected character, or with exact `.` or `..`
- **THEN** the upstream URL percent-encodes the unexpected character and keeps the `/close` suffix, or the call raises `ValueError` and makes no HTTP request

Tests: backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_complete_task_percent_encodes_unexpected_character, backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_complete_task_rejects_dot_segments

## MODIFIED Requirements

### Requirement: Complete a task
The system SHALL close a task on `POST /api/todoist/tasks/<id>/complete/` via `POST {TODOIST_BASE_URL}/tasks/<id>/close` with a validated id, percent-encoded in the path, without parsing a request body. It SHALL return 200 `{"ok": true}`, 503 without an account when the id is valid, and 405 for other methods.
Enforced: backend/todoist_sync/views.py::complete, backend/todoist_sync/service.py::complete_task

#### Scenario: Successful close
- **WHEN** a connected user completes task `6X7rfFVPjhvv84XG` and Todoist answers 2xx
- **THEN** the response is 200 `{"ok": true}` and Todoist received a Bearer POST to `/tasks/6X7rfFVPjhvv84XG/close`

Tests: backend/tests/test_todoist_sync_views.py::TestCompleteView::test_end_to_end_posts_close_with_bearer, backend/tests/test_todoist_sync_views.py::TestCompleteView::test_view_level_delegates_to_service, backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_success_returns_none_and_posts_close, backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_alphanumeric_task_id_round_trips_in_url

#### Scenario: Provider errors on close
- **WHEN** the close call returns 401/403, a 5xx, a connection error or a timeout
- **THEN** the response is 401, 502 or 504 with the error envelope

Tests: backend/tests/test_todoist_sync_views.py::TestCompleteView::test_service_errors_mapped_to_envelopes, backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_401_raises_auth, backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_403_raises_auth, backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_500_raises_provider, backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_connection_error_raises_provider, backend/tests/test_todoist_sync_service.py::TestCompleteTask::test_timeout_raises_timeout

#### Scenario: No account or wrong method
- **WHEN** a user without an account POSTs a valid id, or any user sends GET to the complete route
- **THEN** the response is 503 "No Todoist account configured" or 405 respectively

Tests: backend/tests/test_todoist_sync_views.py::TestCompleteView::test_503_when_no_account, backend/tests/test_todoist_sync_views.py::TestCompleteView::test_get_method_not_allowed
