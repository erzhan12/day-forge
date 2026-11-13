## ADDED Requirements

### Requirement: Complete-task id format
The system SHALL reject a `task_id` that is not a canonical hyphenated UUID on `POST /api/habitica/tasks/<task_id>/complete/` with 400 `{"errors": {"detail": "Invalid task id."}}` and MUST NOT call Habitica, including when the user has no account. The service SHALL percent-encode the id and reject exact `.` and `..`.
Enforced: backend/habitica_sync/schemas.py::is_valid_task_id, backend/habitica_sync/views.py::complete, backend/habitica_sync/service.py::complete_task

#### Scenario: Malformed id
- **WHEN** a connected user POSTs a complete path whose decoded `task_id` is not a canonical hyphenated UUID
- **THEN** the response is 400 `{"errors": {"detail": "Invalid task id."}}` and Habitica is not contacted

Tests: backend/tests/test_habitica_sync_views.py::test_malformed_task_id_returns_400_without_upstream, backend/tests/test_habitica_sync_views.py::test_twice_encoded_slash_returns_400, backend/tests/test_habitica_sync_views.py::TestHabiticaTaskIdValidation::test_invalid_uuid_forms_are_rejected

#### Scenario: Malformed id without an account
- **WHEN** a user with no Habitica account POSTs a malformed `task_id`
- **THEN** the response is 400 with the same envelope, not 503, and Habitica is not contacted

Tests: backend/tests/test_habitica_sync_views.py::test_malformed_task_id_returns_400_without_account

#### Scenario: Id rejected at routing
- **WHEN** the path has an empty `task_id` segment or a decoded slash
- **THEN** the response is 404 and Habitica is not contacted

Tests: backend/tests/test_habitica_sync_views.py::test_empty_task_id_does_not_match_route, backend/tests/test_habitica_sync_views.py::test_decoded_slash_does_not_match_route

#### Scenario: Service encodes and guards path segments
- **WHEN** `complete_task` is called with an unexpected character, or with exact `.` or `..`
- **THEN** the upstream URL percent-encodes the unexpected character and keeps the `/score/up` suffix, or the call raises `ValueError` and makes no HTTP request

Tests: backend/tests/test_habitica_sync_service.py::test_complete_task_percent_encodes_unexpected_character, backend/tests/test_habitica_sync_service.py::test_complete_task_rejects_dot_segments

## MODIFIED Requirements

### Requirement: Complete a task
The system SHALL complete a task with `POST {HABITICA_BASE_URL}/tasks/<id>/score/up` and an empty JSON body, using a validated id percent-encoded in the path, answer `{"ok": true}` on success, and then invalidate the user's task cache by bumping only the account's `updated_at` column. A missing account SHALL return 503 only when the id is valid.
Enforced: backend/habitica_sync/views.py::complete, backend/habitica_sync/service.py::complete_task, backend/habitica_sync/cache.py::invalidate_tasks

#### Scenario: Success
- **WHEN** the user completes a task and Habitica answers 2xx
- **THEN** the response is `{"ok": true}` and `updated_at` advances, which retires every cached list for the account

Tests: backend/tests/test_habitica_sync_views.py::test_complete_invalidates_cache, backend/tests/test_habitica_sync_service.py::test_complete_task_scores_up_with_empty_json_body, backend/tests/test_habitica_sync_views.py::test_end_to_end_posts_score_up_with_valid_id

#### Scenario: Invalidation with a stale row
- **WHEN** the cache is invalidated through an in-memory row that is stale or already deleted
- **THEN** a concurrent token rotation is kept and a deleted row is not re-created

Tests: backend/tests/test_habitica_sync_views.py::test_invalidate_tasks_does_not_clobber_concurrent_token_update, backend/tests/test_habitica_sync_views.py::test_invalidate_tasks_does_not_resurrect_deleted_account

#### Scenario: Errors
- **WHEN** completing fails with a timeout or a misconfigured key
- **THEN** the response is 504 or a 500 config envelope, and the cache is not invalidated

Tests: backend/tests/test_habitica_sync_views.py::test_complete_error_mapping, backend/tests/test_habitica_sync_views.py::test_complete_maps_improperly_configured_to_500

#### Scenario: No account
- **WHEN** a user without a Habitica account completes a task with a valid id
- **THEN** the response is 503 with code `integration_account_missing` and Habitica is not contacted

Tests: backend/tests/test_habitica_sync_views.py::test_complete_503_without_account
