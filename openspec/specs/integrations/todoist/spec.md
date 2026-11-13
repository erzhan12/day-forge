# integrations/todoist Specification

## Purpose
Read-and-complete integration with Todoist through a per-user personal API token. A user connects, re-verifies or disconnects one token. The server encrypts it at rest and lists that user's active tasks for a schedule date, with overdue carry-over on the user's local today. Lists are served from a versioned cache, and closing a task invalidates them. Task text is display-only and never reaches the AI provider.

## Requirements

### Requirement: Account status never exposes the token
The system SHALL answer `GET /api/todoist/account/` with only `connected` and `last_verified_at` (ISO string or null), returning `connected: false` when the user has no `TodoistAccount`.
Enforced: backend/todoist_sync/views.py::account, backend/todoist_sync/views.py::_account_status_payload

#### Scenario: No account
- **WHEN** a logged-in user without a Todoist account requests the status
- **THEN** the response is 200 `{"connected": false, "last_verified_at": null}`

Tests: backend/tests/test_todoist_sync_views.py::TestAccountGet::test_returns_disconnected_status

#### Scenario: Connected account
- **WHEN** the user has a stored account
- **THEN** the response is 200 with `connected: true`, its `last_verified_at`, and no token-shaped field

Tests: backend/tests/test_todoist_sync_views.py::TestAccountGet::test_returns_connected_status_when_account_present

### Requirement: Connect payload validation
The system SHALL reject a `POST /api/todoist/account/` body with 400 when it is invalid JSON, not an object, or has a missing, blank or longer-than-128-character `token`, using per-field `errors` plus `detail`. It SHALL store the token with surrounding whitespace stripped.
Enforced: backend/todoist_sync/schemas.py::validate_account_payload, backend/common/http.py::parse_json_object

#### Scenario: Missing token
- **WHEN** the body omits `token`
- **THEN** the response is 400 with `errors.token` set and nothing is persisted

Tests: backend/tests/test_todoist_sync_views.py::TestAccountPost::test_post_missing_token_returns_400_envelope

#### Scenario: Blank or oversized token
- **WHEN** `token` is whitespace-only or longer than 128 characters
- **THEN** the response is 400 with a per-field `errors.token` message

Tests: backend/tests/test_todoist_sync_views.py::TestAccountPost::test_post_empty_token_returns_400_per_field, backend/tests/test_todoist_sync_views.py::TestAccountPost::test_post_token_too_long_returns_400_per_field

#### Scenario: Malformed JSON
- **WHEN** the body is not valid JSON
- **THEN** the response is 400 with the standard error envelope

Tests: backend/tests/test_todoist_sync_views.py::TestAccountPost::test_post_invalid_json_returns_400_envelope

### Requirement: Connect rate limit
The system SHALL charge each validated connect POST, including failed verifications, against a per-user hourly fixed-window counter `connect_rl:todoist:<user_id>` capped by `TODOIST_CONNECT_RATE_LIMIT_PER_HOUR`. Over budget it SHALL return 429 with `Retry-After` and skip verification.
Enforced: backend/todoist_sync/views.py::account, backend/schedules/ratelimit.py::consume_rate_limit

#### Scenario: Budget exhausted
- **WHEN** a user exceeds the hourly connect budget
- **THEN** the response is 429 "Rate limit exceeded. Try again later." and Todoist is not called

Tests: backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_returns_429_once_connect_budget_exceeded, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_429_short_circuits_before_verify_credentials, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_counter_stored_under_expected_key

#### Scenario: Failed verification still counts
- **WHEN** verification fails with an auth error
- **THEN** the attempt consumes one unit of the budget

Tests: backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_failed_verify_still_consumes_token

#### Scenario: Rejected bodies and reads are free
- **WHEN** a POST fails validation (400) or size checks (413), or the user calls GET or DELETE
- **THEN** no rate-limit unit is consumed

Tests: backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_pre_validation_does_not_consume_token, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_get_and_delete_not_rate_limited

### Requirement: Verify-then-upsert connect
The system SHALL verify the token with one authenticated `GET {TODOIST_BASE_URL}/projects?limit=1` before persisting. On success it SHALL upsert the user's single account row with the encrypted token, `last_verified_at = now` and a bumped `updated_at`. On failure nothing is persisted.
Enforced: backend/todoist_sync/views.py::account, backend/todoist_sync/service.py::verify_credentials

#### Scenario: Valid token
- **WHEN** Todoist accepts the token
- **THEN** the response is 200 with `connected: true` and the stored ciphertext decrypts to the submitted token

Tests: backend/tests/test_todoist_sync_views.py::TestAccountPost::test_post_persists_encrypted_password, backend/tests/test_todoist_sync_service.py::TestVerifyCredentials::test_success_returns_none

#### Scenario: Rejected token
- **WHEN** Todoist answers 401 or 403
- **THEN** the response is 401 with code `integration_credentials_error`, the account state is reported, and no row is written

Tests: backend/tests/test_todoist_sync_views.py::TestAccountPost::test_post_invalid_credentials_does_not_persist, backend/tests/test_integration_infrastructure.py::test_failed_account_verification_is_not_session_expiry, backend/tests/test_todoist_sync_service.py::TestVerifyCredentials::test_401_raises_auth, backend/tests/test_todoist_sync_service.py::TestVerifyCredentials::test_403_raises_auth

#### Scenario: Timeout or provider failure
- **WHEN** the verification call times out, or Todoist returns another non-2xx or a connection error
- **THEN** the response is 504 or 502 with the error envelope and nothing is persisted

Tests: backend/tests/test_todoist_sync_views.py::TestAccountPost::test_post_timeout_returns_504_envelope, backend/tests/test_todoist_sync_views.py::TestAccountPost::test_post_provider_failure_returns_502_envelope, backend/tests/test_todoist_sync_service.py::TestVerifyCredentials::test_timeout_raises_timeout, backend/tests/test_todoist_sync_service.py::TestVerifyCredentials::test_500_raises_provider, backend/tests/test_todoist_sync_service.py::TestVerifyCredentials::test_connection_error_raises_provider

#### Scenario: Encryption key misconfigured on save
- **WHEN** verification succeeds but `TODOIST_ENCRYPTION_KEY` is unusable
- **THEN** the response is 500 "Todoist service is misconfigured. Contact the administrator." with code `integration_configuration_error`

### Requirement: Idempotent disconnect
The system SHALL delete the user's `TodoistAccount` on `DELETE /api/todoist/account/` and return the disconnected status payload, whether or not a row existed.
Enforced: backend/todoist_sync/views.py::account

#### Scenario: Delete existing account
- **WHEN** a connected user disconnects
- **THEN** the row is removed and the response is 200 `{"connected": false, "last_verified_at": null}`

Tests: backend/tests/test_todoist_sync_views.py::TestAccountDelete::test_delete_removes_row

#### Scenario: Delete with no account
- **WHEN** a user with no account disconnects
- **THEN** the response is the same 200 disconnected payload

Tests: backend/tests/test_todoist_sync_views.py::TestAccountDelete::test_delete_is_idempotent

#### Scenario: Reads after disconnect
- **WHEN** tasks were cached and the user then disconnects
- **THEN** the next tasks request returns 503 instead of cached tasks

Tests: backend/tests/test_todoist_sync_views.py::TestCacheInvalidation::test_cache_invalidates_on_account_delete

### Requirement: Token encryption at rest
The system MUST store the Todoist token only as Fernet ciphertext under `TODOIST_ENCRYPTION_KEY`. It SHALL raise `ImproperlyConfigured` with a safe message when the key is missing, malformed or cannot decrypt the stored row.
Enforced: backend/todoist_sync/crypto.py::encrypt_token, backend/todoist_sync/crypto.py::decrypt_token, backend/todoist_sync/models.py::TodoistAccount

#### Scenario: Key rotated after storage
- **WHEN** the stored ciphertext was written with a different key
- **THEN** decryption raises `ImproperlyConfigured` rather than a provider error

Tests: backend/tests/test_integration_infrastructure.py::test_existing_fernet_ciphertext_and_key_failures, backend/tests/test_todoist_sync_service.py::TestDecryptionPropagation::test_key_rotation_surfaces_as_improperly_configured

#### Scenario: Keys are per provider
- **WHEN** a Todoist ciphertext is decrypted with another integration's key
- **THEN** decryption fails

Tests: backend/tests/test_integration_infrastructure.py::test_provider_keys_remain_independent

### Requirement: Service boundary owns the plaintext token
The system SHALL decrypt the token only inside `fetch_tasks_for_date` and `complete_task`, send it only as a Bearer `Authorization` header, and MUST NOT log it.
Enforced: backend/todoist_sync/service.py::fetch_tasks_for_date, backend/todoist_sync/service.py::complete_task, backend/todoist_sync/service.py::_headers

#### Scenario: Single decryption per call
- **WHEN** tasks are fetched or a task is completed
- **THEN** `get_token` is called exactly once and the request carries `Authorization: Bearer <token>`

Tests: backend/tests/test_todoist_sync_service.py::TestTokenBoundary::test_get_token_called_only_in_fetch, backend/tests/test_todoist_sync_service.py::TestTokenBoundary::test_complete_calls_get_token_once_with_bearer

#### Scenario: Token absent from logs
- **WHEN** fetch or complete runs with logging captured
- **THEN** the plaintext token does not appear in any log record

Tests: backend/tests/test_todoist_sync_service.py::TestCredentialsNeverLogged::test_token_never_appears_in_logs, backend/tests/test_todoist_sync_service.py::TestCredentialsNeverLogged::test_token_never_appears_in_logs_complete

### Requirement: Date-scoped task filter
The system SHALL query `GET {TODOIST_BASE_URL}/tasks/filter` with `"<date> | overdue"` when the date equals today in the user's saved schedule timezone, and with the bare `"<date>"` otherwise. Today SHALL come from one clock snapshot per request.
Enforced: backend/todoist_sync/service.py::_filter_query, backend/todoist_sync/service.py::is_user_today, backend/todoist_sync/views.py::tasks

#### Scenario: Today includes overdue
- **WHEN** the requested date is the user's local today
- **THEN** the filter query is `"<date> | overdue"`

Tests: backend/tests/test_todoist_sync_service.py::TestFilterQuerySelection::test_today_uses_date_overdue, backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_today_uses_date_overdue_filter, backend/tests/test_todoist_sync_service.py::TestFilterQuerySelection::test_explicit_user_today_overrides_project_today

#### Scenario: Other dates are exact
- **WHEN** the requested date is in the past or future relative to local today
- **THEN** the filter query is the literal `"<date>"`

Tests: backend/tests/test_todoist_sync_service.py::TestFilterQuerySelection::test_past_date_uses_literal_date_token, backend/tests/test_todoist_sync_service.py::TestFilterQuerySelection::test_future_date_uses_literal_date_token, backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_other_date_uses_exact_date_filter

#### Scenario: Saved timezone decides today
- **WHEN** the saved zone is ahead of UTC (or crosses a DST midnight) so its local date differs from the server's
- **THEN** the overdue filter follows the saved zone's local date

Tests: backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_saved_zone_ahead_of_utc_uses_overdue, backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_dst_local_midnight_selects_filter, backend/tests/test_todoist_sync_service.py::TestFilterQuerySelection::test_direct_account_fetch_uses_saved_timezone

### Requirement: Complete cursor pagination
The system SHALL request filter pages with `limit=200` and follow `next_cursor` until it is empty, concatenating `results`. After 200 pages without a terminating cursor it SHALL raise a provider error instead of truncating.
Enforced: backend/todoist_sync/service.py::_fetch_filtered_tasks, backend/todoist_sync/service.py::_MAX_FILTER_PAGES

#### Scenario: Multiple pages
- **WHEN** the first page returns a non-null `next_cursor`
- **THEN** the next page is requested with that cursor and all results are combined

Tests: backend/tests/test_todoist_sync_service.py::TestPagination::test_pages_are_concatenated, backend/tests/test_todoist_sync_service.py::TestPagination::test_single_page_makes_exactly_one_call, backend/tests/test_todoist_sync_service.py::TestFilterQuerySelection::test_filter_uses_max_page_limit

#### Scenario: Endless cursor
- **WHEN** the endpoint keeps returning a cursor
- **THEN** the fetch raises `TodoistProviderError` after the page ceiling

Tests: backend/tests/test_todoist_sync_service.py::TestPagination::test_endless_cursor_raises_instead_of_looping_forever

### Requirement: Task normalisation and order
The system SHALL return each task as `id`, `title` (from `content`), raw `priority`, `ui_priority` = `"P" + (5 - priority)` and `due_date` (`YYYY-MM-DD` with any time dropped, or null). It SHALL skip malformed tasks and sort by priority desc, due date, casefolded title, id.
Enforced: backend/todoist_sync/service.py::_normalize_task, backend/todoist_sync/service.py::_normalize_due_date, backend/todoist_sync/service.py::fetch_tasks_for_date

#### Scenario: Priority and title mapping
- **WHEN** Todoist returns a task with `priority` 4 and `content` "Write report"
- **THEN** the task has `ui_priority` "P1" and `title` "Write report", with no `content` field

Tests: backend/tests/test_todoist_sync_service.py::TestPriorityMapping::test_priority_maps_to_ui_flag, backend/tests/test_todoist_sync_service.py::TestTitleMapping::test_content_maps_to_title

#### Scenario: Due date forms
- **WHEN** `due.date` is a date, a datetime with or without a zone suffix, or `due` is null
- **THEN** `due_date` is the date part or null, without raising

Tests: backend/tests/test_todoist_sync_service.py::TestDueNormalisation::test_full_day_due_keeps_date, backend/tests/test_todoist_sync_service.py::TestDueNormalisation::test_timed_due_drops_time_no_raise, backend/tests/test_todoist_sync_service.py::TestDueNormalisation::test_timed_due_with_tz_suffix_drops_time_no_raise, backend/tests/test_todoist_sync_service.py::TestDueNormalisation::test_null_due_maps_to_none

#### Scenario: Malformed task and stable sort
- **WHEN** one raw task lacks required fields and others have mixed priorities and null due dates
- **THEN** the malformed task is skipped with a warning and the rest come back in deterministic order

Tests: backend/tests/test_todoist_sync_service.py::TestMalformedTaskSkipped::test_malformed_task_skipped_not_crash, backend/tests/test_todoist_sync_service.py::TestDeterministicSort::test_sort_is_priority_desc_then_due_then_title, backend/tests/test_todoist_sync_service.py::TestDeterministicSort::test_none_due_task_does_not_raise

### Requirement: Tasks endpoint responses
The system SHALL answer `GET /api/todoist/tasks/<date>/` with 200 `{"tasks": [...], "meta": {"account_state": "connected", "resource_state": "ready"}}`. It SHALL return 400 for a non-ISO date and 503 code `integration_account_missing` when the user has no account.
Enforced: backend/todoist_sync/views.py::tasks, backend/common/integration_response.py::resource_error

#### Scenario: Successful fetch
- **WHEN** a connected user requests a valid date
- **THEN** the response is 200 with normalised tasks and ready meta

Tests: backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_fetch_success

#### Scenario: Invalid date
- **WHEN** the date segment is not `YYYY-MM-DD`
- **THEN** the response is 400 "Invalid date format. Use YYYY-MM-DD."

Tests: backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_400_on_invalid_date

#### Scenario: No account
- **WHEN** the user has no Todoist account
- **THEN** the response is 503 "No Todoist account configured" with meta `disconnected` / `unavailable`

Tests: backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_503_when_no_account, backend/tests/test_integration_infrastructure.py::test_missing_account_is_explicit_resource_state

### Requirement: Provider and configuration error mapping
The system SHALL map auth failures to 401 (`credentials_error`), timeouts to 504 (`unavailable`), and other provider failures to 502 (`provider_error`) with meta `account_state: connected`. A decryption `ImproperlyConfigured` SHALL map to 500 `integration_configuration_error`, never 502.
Enforced: backend/todoist_sync/views.py::_service_error_response, backend/todoist_sync/views.py::_SERVICE_ERROR_STATUS, backend/todoist_sync/service.py::_raise_for_status

#### Scenario: Provider failure on fetch
- **WHEN** Todoist returns 401, a 5xx, or the fetch times out
- **THEN** the tasks response is 401, 502 or 504 respectively, with an envelope that omits the raw error text

Tests: backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_auth_error_returns_401_envelope, backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_timeout_returns_504_envelope, backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_provider_failure_returns_502_envelope, backend/tests/test_integration_infrastructure.py::test_resource_failure_preserves_account_state, backend/tests/test_todoist_sync_service.py::TestProviderErrorMapping::test_fetch_401_raises_auth, backend/tests/test_todoist_sync_service.py::TestProviderErrorMapping::test_fetch_timeout_raises_timeout, backend/tests/test_todoist_sync_service.py::TestProviderErrorMapping::test_fetch_500_raises_provider

#### Scenario: Undecryptable token
- **WHEN** the stored token cannot be decrypted during fetch or complete
- **THEN** the response is 500 "Todoist service is misconfigured. Contact the administrator."

Tests: backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_decryption_misconfig_returns_500_with_config_message, backend/tests/test_todoist_sync_views.py::TestCompleteView::test_decryption_misconfig_returns_500_with_config_message, backend/tests/test_todoist_sync_service.py::TestDecryptionPropagation::test_get_token_improperly_configured_propagates

### Requirement: Versioned task cache
The system SHALL cache each successful task list for `TODOIST_CACHE_TTL_SECONDS` under `todoist_tasks:<user_id>:<updated_at iso>:<time_zone>:<date>:<scope>`, with scope `with_overdue` for local today and `exact` otherwise. It SHALL serve a cache hit without calling Todoist.
Enforced: backend/todoist_sync/cache.py::tasks_cache_key, backend/todoist_sync/cache.py::tasks_filter_scope, backend/todoist_sync/views.py::tasks

#### Scenario: Cache hit
- **WHEN** the same date is requested twice within the TTL
- **THEN** only the first request calls Todoist

Tests: backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_cache_hit_short_circuits_second_call

#### Scenario: Scope and timezone separate entries
- **WHEN** the same date is read under the exact and overdue scopes, or the saved timezone changes
- **THEN** each combination uses a distinct cache key

Tests: backend/tests/test_integration_infrastructure.py::test_cache_keys_preserve_provider_identity_and_filter_scope, backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_exact_and_overdue_filters_use_separate_cache_entries, backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_timezone_change_during_fetch_rekeys_cache

#### Scenario: Token rotation invalidates
- **WHEN** the user re-connects with a new token after tasks were cached
- **THEN** the next read misses the cache and calls Todoist

Tests: backend/tests/test_todoist_sync_views.py::TestCacheInvalidation::test_cache_invalidates_on_account_update

### Requirement: Forced refresh
The system SHALL bypass the cache read when `GET /api/todoist/tasks/<date>/` carries `refresh=1`. A successful forced fetch re-warms the entry. A failed one SHALL leave the previously cached list intact.
Enforced: backend/todoist_sync/views.py::tasks

#### Scenario: Refresh re-warms
- **WHEN** a cached date is requested with `?refresh=1` and then without it
- **THEN** the forced request calls Todoist and the following request is a cache hit

Tests: backend/tests/test_todoist_sync_views.py::TestRefreshBypass::test_refresh_bypasses_cache_and_rewarms, backend/tests/test_todoist_sync_views.py::TestRefreshBypass::test_refresh_keeps_saved_zone_overdue_scope

#### Scenario: Failed refresh keeps cache
- **WHEN** a forced refresh gets a provider 500
- **THEN** the refresh returns 502 and a later non-forced read returns the earlier cached list

Tests: backend/tests/test_todoist_sync_views.py::TestTasksEndpoint::test_failed_refresh_preserves_cached_tasks

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

### Requirement: Completion invalidates cached lists
After a successful close, the system SHALL rotate the account's cache version by setting `updated_at = now` through a queryset update. This makes every cached list for the user unreachable without overwriting a concurrently rotated token or re-creating a deleted row.
Enforced: backend/todoist_sync/cache.py::invalidate_tasks, backend/common/integration_cache.py::invalidate_account_version

#### Scenario: Closed task not served stale
- **WHEN** tasks are cached, one is completed, and the date is read again
- **THEN** the read calls Todoist and the closed task is absent

Tests: backend/tests/test_todoist_sync_views.py::TestCompleteView::test_complete_invalidates_cache

#### Scenario: Stale instance during concurrent change
- **WHEN** invalidation runs on an in-memory account after the token was rotated or the row deleted
- **THEN** the new token is kept and the deleted row stays deleted

Tests: backend/tests/test_todoist_sync_views.py::TestCacheInvalidation::test_invalidate_tasks_does_not_clobber_concurrent_token_update, backend/tests/test_todoist_sync_views.py::TestCacheInvalidation::test_invalidate_tasks_does_not_resurrect_deleted_account

### Requirement: Authentication and CSRF
The system SHALL require a logged-in session for every Todoist endpoint and SHALL enforce CSRF on the account POST/DELETE and the complete POST.
Enforced: backend/todoist_sync/views.py::account, backend/todoist_sync/views.py::tasks, backend/todoist_sync/views.py::complete

#### Scenario: Anonymous request
- **WHEN** an anonymous client calls the account, tasks or complete endpoint
- **THEN** the request is rejected and no Todoist data is returned

Tests: backend/tests/test_todoist_sync_views.py::TestAuthGuard::test_anonymous_account_get_redirects_to_login, backend/tests/test_todoist_sync_views.py::TestAuthGuard::test_anonymous_tasks_redirects_to_login, backend/tests/test_todoist_sync_views.py::TestCompleteView::test_anonymous_complete_redirects_to_login

#### Scenario: Missing CSRF token
- **WHEN** a logged-in client without a CSRF token sends a mutating request
- **THEN** the response is 403

Tests: backend/tests/test_todoist_sync_views.py::TestCsrfGuard::test_post_without_csrf_token_returns_403, backend/tests/test_todoist_sync_views.py::TestCsrfGuard::test_delete_without_csrf_token_returns_403, backend/tests/test_todoist_sync_views.py::TestCompleteView::test_post_without_csrf_token_returns_403

### Requirement: Encryption key startup check
When `DEBUG=False`, the system SHALL fail system checks with `todoist_sync.E001` if `TODOIST_ENCRYPTION_KEY` is empty or is not a valid Fernet key. With `DEBUG=True` it SHALL raise no error.
Enforced: backend/todoist_sync/checks.py::error_todoist_encryption_key_missing_in_production

#### Scenario: Missing or malformed key in production
- **WHEN** `DEBUG=False` and the key is empty or malformed
- **THEN** one `todoist_sync.E001` error naming `TODOIST_ENCRYPTION_KEY` is reported

Tests: backend/tests/test_todoist_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_fires_when_key_missing_in_prod, backend/tests/test_todoist_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_fires_when_key_is_malformed_in_prod

#### Scenario: Debug or valid key
- **WHEN** `DEBUG=True`, or `DEBUG=False` with a valid key
- **THEN** no E001 error is reported

Tests: backend/tests/test_todoist_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_silent_when_debug_true, backend/tests/test_todoist_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_silent_when_key_set_in_prod, backend/tests/test_todoist_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_silent_when_malformed_key_in_debug

### Requirement: Non-shared cache warning
When `DEBUG=False`, at least one `TodoistAccount` exists and the default cache is LocMem, FileBased or Dummy, the system SHALL emit the non-blocking warning `todoist_sync.W001`. It SHALL emit nothing if the accounts table cannot be queried yet.
Enforced: backend/todoist_sync/checks.py::warn_ineffective_cache_with_todoist_sync, backend/common/integration_checks.py::ineffective_cache_with_accounts

#### Scenario: Ineffective backend with accounts
- **WHEN** a production config uses an ineffective cache backend and an account exists
- **THEN** a `todoist_sync.W001` warning is reported

Tests: backend/tests/test_todoist_sync_checks.py::TestW001IneffectiveCache::test_w001_fires_with_locmem_and_account, backend/tests/test_todoist_sync_checks.py::TestW001IneffectiveCache::test_w001_fires_with_each_ineffective_backend

#### Scenario: Silent cases
- **WHEN** no account exists, the cache is shared, `DEBUG=True`, or the table does not exist yet
- **THEN** no W001 warning is reported

Tests: backend/tests/test_todoist_sync_checks.py::TestW001IneffectiveCache::test_w001_silent_with_no_account, backend/tests/test_todoist_sync_checks.py::TestW001IneffectiveCache::test_w001_silent_with_shared_cache, backend/tests/test_todoist_sync_checks.py::TestW001IneffectiveCache::test_w001_silent_when_debug_true, backend/tests/test_todoist_sync_checks.py::TestW001IneffectiveCache::test_w001_swallows_db_error_during_first_migrate

### Requirement: Todoist settings and import-time validation
The system SHALL read `TODOIST_BASE_URL` (default `https://api.todoist.com/api/v1`), `TODOIST_REQUEST_TIMEOUT` (10), `TODOIST_CACHE_TTL_SECONDS` (300) and `TODOIST_CONNECT_RATE_LIMIT_PER_HOUR` (20). Import SHALL raise `ValueError` when any of the last three is `<= 0`.
Enforced: backend/day_forge/settings.py::TODOIST_BASE_URL, backend/day_forge/settings.py::TODOIST_REQUEST_TIMEOUT, backend/day_forge/settings.py::TODOIST_CACHE_TTL_SECONDS

#### Scenario: Connect limit default and guard
- **WHEN** `TODOIST_CONNECT_RATE_LIMIT_PER_HOUR` is unset, or set to 0 or a negative value
- **THEN** the setting is 20, or settings import raises `ValueError`

Tests: backend/tests/test_settings_validation.py::test_connect_rate_limit_default_is_twenty, backend/tests/test_settings_validation.py::test_non_positive_connect_rate_limit_raises_at_import

#### Scenario: Non-positive timeout or TTL
- **WHEN** `TODOIST_REQUEST_TIMEOUT` or `TODOIST_CACHE_TTL_SECONDS` is `<= 0`
- **THEN** settings import raises `ValueError`

### Requirement: Read-only admin without ciphertext
The system SHALL register `TodoistAccount` in the Django admin as read-only. It SHALL show only user, `last_verified_at`, `created_at` and `updated_at`, never render `token_encrypted`, and deny add and change.
Enforced: backend/todoist_sync/admin.py::TodoistAccountAdmin

#### Scenario: Admin view of an account
- **WHEN** a staff user opens a Todoist account in the admin
- **THEN** the token ciphertext is not shown and the record cannot be added or edited

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
