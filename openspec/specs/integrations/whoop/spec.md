# integrations/whoop Specification

## Purpose
TBD - created by archiving change 0107-whoop-export. Update Purpose after archive.

## Requirements

### Requirement: WHOOP settings are all or none
WHOOP SHALL be disabled when no `WHOOP_OAUTH_*` setting is set, without blocking boot. When any is set, a system check SHALL require all four and a valid Fernet key.
Enforced: backend/whoop_sync/checks.py::error_whoop_oauth_partial_config

#### Scenario: Partial configuration
- **WHEN** only some `WHOOP_OAUTH_*` settings are set
- **THEN** the WHOOP system check reports an error

Tests: backend/tests/test_whoop_sync_models.py::TestE001AllOrNone::test_partial_config_errors_in_every_mode

#### Scenario: No configuration
- **WHEN** no `WHOOP_OAUTH_*` setting is set
- **THEN** the check passes and the WHOOP routes report WHOOP as not configured

Tests: backend/tests/test_whoop_sync_models.py::TestE001AllOrNone::test_none_set_passes_in_production, backend/tests/test_whoop_sync_views.py::TestConnect::test_not_configured

### Requirement: WHOOP connect and callback
`connect` SHALL require a logged-in session and redirect to WHOOP consent with an 8-character `state` stored in the session. The callback SHALL accept a code only when `state` matches the stored value (compared in constant time, used once), then store the tokens Fernet-encrypted, replacing any earlier account for that user.
Enforced: backend/whoop_sync/views.py::connect, backend/whoop_sync/views.py::callback

#### Scenario: State mismatch
- **WHEN** the callback arrives with a missing or different `state`
- **THEN** no tokens are exchanged or stored and the result page reports failure

Tests: backend/tests/test_whoop_sync_views.py::TestCallback::test_state_problems_fail_without_exchange, backend/tests/test_whoop_sync_views.py::TestCallback::test_state_is_single_use

#### Scenario: Reconnect
- **WHEN** a user who already has a WHOOP account completes the flow again
- **THEN** the existing account row is updated instead of a second one being created

Tests: backend/tests/test_whoop_sync_views.py::TestCallback::test_reconnect_updates_the_existing_row

### Requirement: WHOOP token refresh is single-flight
At most one refresh per WHOOP account SHALL run at a time, behind a shared-cache lock. The holder SHALL persist the rotated refresh token immediately; other requests SHALL wait for the stored token and fail as transient (502) if none appears.
Enforced: backend/whoop_sync/service.py::ensure_access_token, backend/whoop_sync/service.py::_wait_for_refresh

#### Scenario: Concurrent requests with an expired token
- **WHEN** two requests need a refresh at the same time
- **THEN** WHOOP's token endpoint is called once and both requests use the stored new token

Tests: backend/tests/test_whoop_sync_tokens.py::test_concurrent_requests_refresh_once_on_separate_sqlite_connections, backend/tests/test_whoop_sync_tokens.py::TestWaiter::test_waiter_picks_up_the_token_the_holder_stores, backend/tests/test_whoop_sync_tokens.py::TestWaiter::test_waiter_times_out_as_transient_not_reconnect

#### Scenario: Refresh rejected
- **WHEN** the refresh is rejected and no fresher token is stored
- **THEN** the export reports that WHOOP must be reconnected (409)

Tests: backend/tests/test_whoop_sync_tokens.py::TestLockHolder::test_rejected_refresh_without_fresher_token_requires_reconnect, backend/tests/test_whoop_export_api.py::TestErrors::test_rejected_refresh_is_409

### Requirement: WHOOP export route
`GET /api/export/whoop/<date>/` SHALL authenticate like the daily export and return the day's recovery, sleep, previous-day strain and workouts as Markdown with `Cache-Control: private, no-store`. Statuses: 400 bad date, 401 auth, 404 not connected, 409 reconnect required, 429 WHOOP rate limit, 502 WHOOP failure.
Enforced: backend/whoop_sync/views.py::whoop_export, backend/schedules/export_auth.py::resolve_export_owner

#### Scenario: Not connected
- **WHEN** the owner has no WHOOP account
- **THEN** the response is 404 and no WHOOP call is made

Tests: backend/tests/test_whoop_export_api.py::TestErrors::test_not_connected_is_404_without_whoop_calls

#### Scenario: Provider failure
- **WHEN** WHOOP returns a 5xx or is unreachable
- **THEN** the response is 502 and the WHOOP response body is not passed on

Tests: backend/tests/test_whoop_export_api.py::TestErrors::test_provider_failure_is_502_without_the_body

### Requirement: WHOOP data is not retained
WHOOP health data SHALL NOT be stored, cached, logged or sent to the AI chat or draft providers. Only the encrypted tokens and their metadata are stored.
Enforced: backend/whoop_sync/models.py::WhoopAccount, backend/whoop_sync/views.py::whoop_export

#### Scenario: Export request
- **WHEN** a WHOOP summary is served
- **THEN** no WHOOP payload is written to the database, cache or logs

Tests: backend/tests/test_whoop_export_api.py::TestSuccess::test_stores_caches_and_logs_no_whoop_data, backend/tests/test_whoop_export_api.py::test_ai_packages_never_import_whoop
