# integrations/habitica Specification

## Purpose
The Habitica integration connects one Habitica account per user with a User ID and an API token. It verifies and stores the account and lists the outstanding todos and due dailies for a schedule date, with a versioned per-scope cache. It can also score a task up. This spec covers the account endpoints, the encrypted token storage, the provider request contract and its error mapping, the startup checks and the `HABITICA_*` settings.

## Requirements

### Requirement: Account status without secrets
The system SHALL answer `GET /api/habitica/account/` with `connected`, `last_verified_at` and the plaintext `api_user_id`, and MUST NOT return any token field.
Enforced: backend/habitica_sync/views.py::account, backend/habitica_sync/views.py::_account_status_payload

#### Scenario: Connected account
- **WHEN** the user has a Habitica account row
- **THEN** the response is 200 with `connected: true`, the stored `api_user_id` and no key containing "token"

Tests: backend/tests/test_habitica_sync_views.py::test_account_status_includes_user_id_but_no_token

#### Scenario: No account
- **WHEN** the user has no Habitica account row
- **THEN** the response is 200 with `{"connected": false, "last_verified_at": null, "api_user_id": null}`

Tests: backend/tests/test_habitica_sync_views.py::test_account_status_disconnected_shape

### Requirement: Connect payload validation
The system SHALL require `api_user_id` and `api_token` as non-blank strings of at most 128 characters each, store them stripped of surrounding whitespace, and reject an invalid body with 400 and per-field messages in the `errors` object before any rate-limit or provider work.
Enforced: backend/habitica_sync/schemas.py::validate_account_payload, backend/habitica_sync/views.py::account

#### Scenario: Blank fields
- **WHEN** the client posts an empty `api_user_id` and an empty `api_token`
- **THEN** the response is 400 and `errors` contains both `api_user_id` and `api_token`

Tests: backend/tests/test_habitica_sync_views.py::test_post_validation_errors

#### Scenario: Oversized or malformed body
- **WHEN** the request body exceeds the shared request-size cap, or is not valid JSON
- **THEN** the response is 413 or 400 respectively, no provider call is made and no account row is written

Tests: backend/tests/test_habitica_sync_views.py::test_account_post_rejects_oversized_body, backend/tests/test_http_json.py::test_invalid_encoding_uses_existing_endpoint_envelope

### Requirement: Connect rate limit
The system SHALL consume one token of the per-user fixed one-hour window `connect_rl:habitica:<user_id>` for each validated connect attempt before verifying credentials, and SHALL answer 429 with `Retry-After: 3600` once the count exceeds `HABITICA_CONNECT_RATE_LIMIT_PER_HOUR`.
Enforced: backend/habitica_sync/views.py::account, backend/schedules/ratelimit.py::consume_rate_limit, backend/schedules/ratelimit.py::rate_limited_response

#### Scenario: Budget exhausted
- **WHEN** the user has already made `HABITICA_CONNECT_RATE_LIMIT_PER_HOUR` validated connect attempts in the window
- **THEN** the next attempt returns 429 with the rate-limit detail and Habitica is not contacted

Tests: backend/tests/test_habitica_sync_views.py::TestConnectRateLimit, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_returns_429_once_connect_budget_exceeded, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_429_short_circuits_before_verify_credentials

#### Scenario: Failed verification still counts
- **WHEN** Habitica rejects the credentials
- **THEN** the attempt is still counted under `connect_rl:habitica:<user_id>`

Tests: backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_failed_verify_still_consumes_token, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_counter_stored_under_expected_key

#### Scenario: Invalid body is not counted
- **WHEN** the body is empty, oversized or malformed
- **THEN** the request fails with 400 or 413 without consuming a token

Tests: backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_pre_validation_does_not_consume_token

### Requirement: Verify then upsert the account
The system SHALL verify credentials with one authenticated `GET {HABITICA_BASE_URL}/tasks/user?type=todos` probe, and only on success upsert the user's single account row under a row lock with the new User ID, the encrypted token and `last_verified_at` set to now, returning the connected status.
Enforced: backend/habitica_sync/views.py::account, backend/habitica_sync/service.py::verify_credentials, backend/habitica_sync/models.py::HabiticaAccount

#### Scenario: Valid credentials
- **WHEN** the client posts valid credentials and Habitica accepts them
- **THEN** the response is 200 with the connected status, and the stored token decrypts to the posted token while the stored bytes differ from it

Tests: backend/tests/test_habitica_sync_views.py::test_post_verifies_and_persists_encrypted_token

#### Scenario: Rejected credentials on first connect
- **WHEN** Habitica answers 401 or 403 and the user has no account row
- **THEN** the response is 401 with code `integration_credentials_error`, meta `account_state: "disconnected"` and `resource_state: "credentials_error"`, and the provider message is not echoed

Tests: backend/tests/test_habitica_sync_views.py::test_post_auth_failure_maps_to_401, backend/tests/test_integration_infrastructure.py::test_failed_account_verification_is_not_session_expiry

#### Scenario: Encryption key misconfigured on connect
- **WHEN** verification succeeds but encrypting the token raises `ImproperlyConfigured`
- **THEN** the response is a 500 config envelope with `account_state: "configuration_error"` and the transaction rolls back, leaving no account row

Tests: backend/tests/test_habitica_sync_views.py::test_account_post_maps_improperly_configured_to_500

### Requirement: Disconnect
The system SHALL delete the user's Habitica account row on `DELETE /api/habitica/account/` and return the disconnected status shape, also when no row exists.
Enforced: backend/habitica_sync/views.py::account

#### Scenario: Disconnect
- **WHEN** the user sends `DELETE /api/habitica/account/`
- **THEN** any account row for that user is removed and the response is 200 with `connected: false`

### Requirement: Provider request headers and redirects
The system SHALL send `x-api-user`, `x-api-key`, `x-client: {HABITICA_CLIENT_ID}-DayForge` and `Content-Type: application/json` on every Habitica call, with timeout `HABITICA_REQUEST_TIMEOUT`, and MUST NOT follow redirects on any call that carries the token.
Enforced: backend/habitica_sync/service.py::_headers, backend/habitica_sync/service.py::verify_credentials, backend/habitica_sync/service.py::_fetch_tasks, backend/habitica_sync/service.py::complete_task

#### Scenario: Header set
- **WHEN** headers are built for a User ID and token
- **THEN** they contain both credentials and the `-DayForge` suffixed client id

Tests: backend/tests/test_habitica_sync_service.py::test_headers_include_habitica_auth_and_x_client

#### Scenario: Redirects disabled
- **WHEN** the service verifies, fetches or completes
- **THEN** every outbound call is made with `allow_redirects=False`

Tests: backend/tests/test_habitica_sync_service.py::test_every_outbound_call_disables_redirects

### Requirement: Provider error classification
The system SHALL map Habitica 401/403 to an auth error, other non-2xx statuses, a `success: false` envelope or non-list `data` on task reads to a provider error, a request timeout to a timeout error, and any other request failure to a provider error.
Enforced: backend/habitica_sync/service.py::_raise_for_status, backend/habitica_sync/service.py::_unwrap_task_envelope, backend/habitica_sync/service.py::fetch_tasks_for_date

#### Scenario: Malformed envelope
- **WHEN** a task read returns `success: false` or a non-list `data`
- **THEN** a `HabiticaProviderError` is raised

Tests: backend/tests/test_habitica_sync_service.py::test_success_false_or_non_list_data_raises_provider

#### Scenario: Timeout
- **WHEN** the HTTP call times out
- **THEN** a `HabiticaTimeoutError` is raised

Tests: backend/tests/test_habitica_sync_service.py::test_timeout_maps_to_typed_error

### Requirement: Todo selection by date
The system SHALL fetch `type=todos`, drop completed todos and, for the user's local today, keep todos due today, undated and overdue. For any other date it SHALL keep only todos due exactly on that date. Todos that fail to normalise are skipped.
Enforced: backend/habitica_sync/service.py::fetch_tasks_for_date, backend/habitica_sync/service.py::_include_todo

#### Scenario: Today with overdue carry
- **WHEN** the target date equals the user's local today
- **THEN** due-today, overdue and undated open todos are returned and completed and future todos are not

Tests: backend/tests/test_habitica_sync_service.py::test_fetch_filters_todos_and_due_dailies_for_client_today, backend/tests/test_habitica_sync_service.py::test_user_today_uses_target_date_boundary_for_todos_and_dailies

#### Scenario: Other date
- **WHEN** the target date is not the user's local today
- **THEN** only open todos due exactly on that date are returned

Tests: backend/tests/test_habitica_sync_service.py::test_future_exact_date_skips_dailies_and_undated_overdue

### Requirement: Dailies only for today and only when due
The system SHALL request `type=dailys` only when the target date is the user's local today in the saved time zone, and SHALL return a daily only when Habitica marks it `isDue: true` and it is not completed. Dailies have type `daily` and a null `due_date`.
Enforced: backend/habitica_sync/service.py::fetch_tasks_for_date, backend/habitica_sync/service.py::_normalize_daily, backend/habitica_sync/service.py::is_user_today

#### Scenario: Today
- **WHEN** the target date is the user's local today
- **THEN** a second request with `type=dailys` is made and only the due, open dailies are returned

Tests: backend/tests/test_habitica_sync_service.py::test_fetch_filters_todos_and_due_dailies_for_client_today, backend/tests/test_habitica_sync_service.py::test_direct_account_fetch_uses_saved_timezone

#### Scenario: Not today
- **WHEN** the target date is not the user's local today
- **THEN** only the `type=todos` request is made

Tests: backend/tests/test_habitica_sync_service.py::test_future_exact_date_skips_dailies_and_undated_overdue

### Requirement: Task ordering and shape
The system SHALL list dailies before todos and keep Habitica's API array order within each type, and SHALL serialise each task as `id`, `title`, `type`, `due_date` and `completed`.
Enforced: backend/habitica_sync/service.py::fetch_tasks_for_date, backend/habitica_sync/schemas.py::normalized_task_to_dict

#### Scenario: Order follows the API
- **WHEN** Habitica returns tasks whose array order contradicts due-date and title order
- **THEN** dailies come first, then todos, each in the API array order, and filtered-out tasks do not change the relative order of the rest

Tests: backend/tests/test_habitica_sync_service.py::test_fetch_preserves_api_array_order_within_type, backend/tests/test_habitica_sync_service.py::test_fetch_filtered_subset_preserves_relative_api_order

### Requirement: Task list endpoint
The system SHALL serve `GET /api/habitica/tasks/<date>/` as `{"tasks": [...], "meta": {"account_state": "connected", "resource_state": "ready"}}`, computing local today from the user's saved time zone at request time, and SHALL reject a non-ISO date with 400 before any provider call.
Enforced: backend/habitica_sync/views.py::tasks

#### Scenario: Malformed date
- **WHEN** the date segment is not `YYYY-MM-DD`
- **THEN** the response is 400 and the provider is not called

Tests: backend/tests/test_habitica_sync_views.py::test_tasks_rejects_malformed_date

#### Scenario: Local midnight decides today
- **WHEN** the request instant falls on either side of local midnight, including across a DST change
- **THEN** the service receives the local date of the saved time zone as `local_today`

Tests: backend/tests/test_habitica_sync_views.py::test_dst_local_midnight_selects_habitica_scope, backend/tests/test_habitica_sync_views.py::test_habitica_midnight_rekeys_today_scope

#### Scenario: No account
- **WHEN** the user has no Habitica account
- **THEN** the response is 503 with code `integration_account_missing` and meta `account_state: "disconnected"`, `resource_state: "unavailable"`

Tests: backend/tests/test_habitica_sync_views.py::test_tasks_503_without_account, backend/tests/test_integration_infrastructure.py::test_missing_account_is_explicit_resource_state

### Requirement: Versioned per-scope task cache
The system SHALL cache each serialised task list for `HABITICA_CACHE_TTL_SECONDS` under `habitica_tasks:<user_id>:<updated_at>:<time_zone>:<date>:<scope>`, where scope is `with_overdue` for local today and `exact` otherwise. `refresh=1` SHALL bypass the read and re-warm the cache.
Enforced: backend/habitica_sync/cache.py::tasks_cache_key, backend/habitica_sync/cache.py::tasks_filter_scope, backend/habitica_sync/views.py::tasks

#### Scenario: Hit, miss and refresh
- **WHEN** the same date is read twice and then with `refresh=1`
- **THEN** the second read is served from cache and the refresh calls the provider again

Tests: backend/tests/test_habitica_sync_views.py::test_tasks_cache_hit_miss_and_refresh

#### Scenario: Key includes scope and time zone
- **WHEN** keys are built for the same account and date with the two scopes, or before and after a time-zone change
- **THEN** the keys differ

Tests: backend/tests/test_integration_infrastructure.py::test_cache_keys_preserve_provider_identity_and_filter_scope, backend/tests/test_habitica_sync_views.py::test_timezone_change_during_fetch_rekeys_habitica_cache

#### Scenario: Failed refresh keeps the cached list
- **WHEN** a `refresh=1` read fails at the provider
- **THEN** the error is returned and the earlier cached list is still served to the next normal read

Tests: backend/tests/test_habitica_sync_views.py::test_habitica_failed_refresh_preserves_cached_tasks

### Requirement: Task read error mapping
The system SHALL map task-read failures to resource envelopes that keep `account_state: "connected"`: auth to 401 `credentials_error`, provider to 502 `provider_error`, timeout to 504 `unavailable`, and `ImproperlyConfigured` to a 500 with `account_state: "configuration_error"`. Provider messages are not echoed.
Enforced: backend/habitica_sync/views.py::tasks, backend/habitica_sync/views.py::_service_error_response, backend/common/integration_response.py::resource_error

#### Scenario: Provider failures
- **WHEN** the fetch raises an auth, provider or timeout error
- **THEN** the status is 401, 502 or 504 with the matching code and `account_state: "connected"`

Tests: backend/tests/test_integration_infrastructure.py::test_resource_failure_preserves_account_state, backend/tests/test_habitica_sync_views.py::test_tasks_maps_provider_error_to_502

#### Scenario: Key rotated
- **WHEN** decrypting the stored token raises `ImproperlyConfigured`
- **THEN** the response is a 500 with the misconfiguration detail

Tests: backend/tests/test_habitica_sync_views.py::test_tasks_maps_improperly_configured_to_500

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

### Requirement: Token encryption at rest
The system SHALL store the API token only as Fernet ciphertext under `HABITICA_ENCRYPTION_KEY`, decrypt it only inside the service fetch and complete paths, and raise `ImproperlyConfigured` without the plaintext or ciphertext when the key is missing, malformed or does not match.
Enforced: backend/habitica_sync/crypto.py::encrypt_token, backend/habitica_sync/crypto.py::decrypt_token, backend/habitica_sync/models.py::HabiticaAccount.get_token

#### Scenario: Key mismatch
- **WHEN** a token was encrypted under another key, including another provider's key
- **THEN** decryption raises `ImproperlyConfigured` that names the setting and leaks neither plaintext nor ciphertext

Tests: backend/tests/test_integration_infrastructure.py::test_existing_fernet_ciphertext_and_key_failures, backend/tests/test_integration_infrastructure.py::test_provider_keys_remain_independent

### Requirement: Read-only admin without ciphertext
The system SHALL expose Habitica accounts in the Django admin read-only, with no add or change permission, and MUST NOT render the token ciphertext field.
Enforced: backend/habitica_sync/admin.py::HabiticaAccountAdmin

#### Scenario: Admin view
- **WHEN** an operator opens the Habitica account admin
- **THEN** user, User ID and timestamps are shown read-only and `api_token_encrypted` is absent

### Requirement: Production secrets check
The system SHALL report `habitica_sync.E001` when `DEBUG` is false and `HABITICA_ENCRYPTION_KEY` is empty or not a valid Fernet key, or `HABITICA_CLIENT_ID` is blank. Nothing is reported when `DEBUG` is true.
Enforced: backend/habitica_sync/checks.py::error_habitica_secrets_missing_in_production

#### Scenario: Missing or malformed secrets
- **WHEN** `DEBUG=False` and the key or client id is missing, or the key is malformed
- **THEN** one `habitica_sync.E001` error is reported per problem

Tests: backend/tests/test_habitica_sync_checks.py::test_e001_blocks_debug_false_when_key_or_client_id_missing, backend/tests/test_habitica_sync_checks.py::test_e001_blocks_on_missing_key_only, backend/tests/test_habitica_sync_checks.py::test_e001_blocks_on_missing_client_id_only, backend/tests/test_habitica_sync_checks.py::test_e001_rejects_malformed_key

#### Scenario: Configured or debug
- **WHEN** both secrets are valid, or `DEBUG=True`
- **THEN** no `habitica_sync.E001` is reported

Tests: backend/tests/test_habitica_sync_checks.py::test_e001_silent_when_fully_configured, backend/tests/test_habitica_sync_checks.py::test_e001_allows_debug_true_without_secrets

### Requirement: Shared cache warning
The system SHALL report the non-blocking `habitica_sync.W001` warning when `DEBUG` is false, the default cache is LocMem, FileBased or Dummy, and at least one Habitica account exists. A missing table during the first migrate SHALL suppress it.
Enforced: backend/habitica_sync/checks.py::warn_ineffective_cache_with_habitica_sync, backend/common/integration_checks.py::ineffective_cache_with_accounts

#### Scenario: Ineffective backend with accounts
- **WHEN** `DEBUG=False`, the cache backend is per-process and an account exists
- **THEN** `habitica_sync.W001` is reported

Tests: backend/tests/test_habitica_sync_checks.py::test_w001_warns_on_ineffective_cache_with_account

#### Scenario: Pre-migrate database
- **WHEN** the account table query raises `OperationalError` or `ProgrammingError`
- **THEN** no warning is reported and the check does not fail

Tests: backend/tests/test_habitica_sync_checks.py::test_w001_ignores_pre_migrate_table_absence, backend/tests/test_habitica_sync_checks.py::test_w001_ignores_programming_error

### Requirement: Settings defaults and validation
The system SHALL default `HABITICA_BASE_URL` to `https://habitica.com/api/v3`, `HABITICA_REQUEST_TIMEOUT` to 10, `HABITICA_CACHE_TTL_SECONDS` to 300 and `HABITICA_CONNECT_RATE_LIMIT_PER_HOUR` to 20, and MUST raise `ValueError` at import when any of the last three is `<= 0`.
Enforced: backend/day_forge/settings.py::HABITICA_REQUEST_TIMEOUT, backend/day_forge/settings.py::HABITICA_CACHE_TTL_SECONDS, backend/day_forge/settings.py::HABITICA_CONNECT_RATE_LIMIT_PER_HOUR

#### Scenario: Connect budget
- **WHEN** `HABITICA_CONNECT_RATE_LIMIT_PER_HOUR` is unset, or set to 0 or -1
- **THEN** it defaults to 20, or settings import raises `ValueError` naming it

Tests: backend/tests/test_settings_validation.py::test_connect_rate_limit_default_is_twenty, backend/tests/test_settings_validation.py::test_non_positive_connect_rate_limit_raises_at_import

#### Scenario: Timeout and cache TTL
- **WHEN** `HABITICA_REQUEST_TIMEOUT` or `HABITICA_CACHE_TTL_SECONDS` is set to 0 or less
- **THEN** settings import raises `ValueError` naming the variable

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
