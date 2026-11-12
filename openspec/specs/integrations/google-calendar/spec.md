# integrations/google-calendar Specification

## Purpose
Read-only, multi-account Google Calendar integration under `/api/calendar/google/`. Covers the OAuth
authorization-code web flow (connect, callback, state guard, upsert on reconnect), account listing and
disconnect, encrypted token storage and access-token refresh, per-account event fetch and normalisation
for one local day, the versioned event cache, startup checks and the rule that Google event titles are
display-only and never reach the LLM provider.

## Requirements

### Requirement: Google routes require login
The system SHALL serve the connect, callback, accounts, account-detail and events routes under `/api/calendar/google/` only to authenticated users.
Enforced: backend/gcal_sync/views.py::connect, backend/gcal_sync/views.py::callback, backend/gcal_sync/views.py::accounts, backend/gcal_sync/views.py::account_detail, backend/gcal_sync/views.py::events

#### Scenario: Anonymous request
- **WHEN** an unauthenticated client calls any of the five Google routes
- **THEN** the response is a 302 redirect to `/accounts/login/`

Tests: backend/tests/test_gcal_sync_views.py::TestAuthGuards::test_requires_login

### Requirement: OAuth connect start
The system SHALL, on `GET /api/calendar/google/connect/`, store a random `state` in the session key `gcal_oauth_state` and 302-redirect to Google's consent URL built with `access_type=offline`, `prompt=consent`, that `state`, no `include_granted_scopes` and no PKCE `code_challenge`.
Enforced: backend/gcal_sync/views.py::connect, backend/gcal_sync/service.py::build_authorization_url, backend/gcal_sync/service.py::_build_flow

#### Scenario: Connect redirects to Google
- **WHEN** a signed-in user calls the connect route
- **THEN** the response redirects to `accounts.google.com` and the session holds `gcal_oauth_state`

Tests: backend/tests/test_gcal_sync_views.py::TestConnect::test_connect_redirects_and_stores_state

#### Scenario: No incremental auth and no PKCE
- **WHEN** the authorization URL is built
- **THEN** it contains neither `include_granted_scopes` nor `code_challenge`, and the flow has `autogenerate_code_verifier` false and no `code_verifier`

Tests: backend/tests/test_gcal_sync_service.py::TestScopeRelaxation::test_authorization_url_omits_include_granted_scopes, backend/tests/test_gcal_sync_service.py::TestScopeRelaxation::test_authorization_url_has_no_pkce_challenge, backend/tests/test_gcal_sync_service.py::TestScopeRelaxation::test_build_flow_disables_code_verifier

### Requirement: Server-side OAuth client configuration and scopes
The system SHALL build the OAuth client config, token URI and `redirect_uri` from `GOOGLE_OAUTH_*` settings only, pass `GOOGLE_OAUTH_SCOPE` split on whitespace as separate scopes, and set `OAUTHLIB_RELAX_TOKEN_SCOPE=1` via `setdefault` when the service module loads.
Enforced: backend/gcal_sync/service.py::_client_config, backend/gcal_sync/service.py::_build_flow, backend/gcal_sync/service.py::_refresh_sync

#### Scenario: Relaxed token scope check
- **WHEN** the gcal_sync service module has been imported and the process environment did not set the variable
- **THEN** `OAUTHLIB_RELAX_TOKEN_SCOPE` equals `1`

Tests: backend/tests/test_gcal_sync_service.py::TestScopeRelaxation::test_relax_token_scope_env_is_set

#### Scenario: Multi-scope setting
- **WHEN** `GOOGLE_OAUTH_SCOPE` holds several space-separated scopes
- **THEN** each scope is passed to the OAuth flow and the refresh credentials as its own list element

### Requirement: OAuth callback guards
The system SHALL, on the callback, pop the session state and redirect to `/settings/?google=error&reason=state` when the query or session state is missing or they differ, then to `reason=denied` when Google sent `error`, then to `reason=missing_code` when no `code` is present, without creating an account.
Enforced: backend/gcal_sync/views.py::callback

#### Scenario: State mismatch
- **WHEN** the session state is `good` and the callback carries `state=evil&code=abc`
- **THEN** it redirects to `google=error&reason=state` and no account exists

Tests: backend/tests/test_gcal_sync_views.py::TestCallback::test_state_mismatch_rejected

#### Scenario: Missing state
- **WHEN** the callback carries a `code` but no session or query state
- **THEN** it redirects to `google=error&reason=state` and no account exists

Tests: backend/tests/test_gcal_sync_views.py::TestCallback::test_missing_state_rejected

#### Scenario: User denied consent
- **WHEN** the state matches and the query carries `error=access_denied`
- **THEN** it redirects to `google=error&reason=denied` and no account exists

Tests: backend/tests/test_gcal_sync_views.py::TestCallback::test_denied_redirects

#### Scenario: Missing code
- **WHEN** the state matches and neither `code` nor `error` is present
- **THEN** it redirects to `google=error&reason=missing_code` and no account exists

Tests: backend/tests/test_gcal_sync_views.py::TestCallback::test_missing_code_redirects

### Requirement: Code exchange and account identity
The system SHALL exchange the code for tokens, reject a missing refresh token with `GoogleCalAuthError`, take identity from a verified `id_token` (else the primary calendar id), probe the grant with one calendar-list call, and redirect to `reason=provider` on any exchange failure.
Enforced: backend/gcal_sync/service.py::exchange_code, backend/gcal_sync/service.py::_identify_and_verify_grant, backend/gcal_sync/views.py::callback

#### Scenario: Successful exchange
- **WHEN** the token endpoint returns refresh and access tokens and a valid `id_token` with `sub-9` / `bob@gmail.com`
- **THEN** the result carries that identity, both tokens and an expiry that is timezone-aware UTC

Tests: backend/tests/test_gcal_sync_service.py::TestExchangeCode::test_returns_account_info

#### Scenario: No refresh token
- **WHEN** the token response has no refresh token
- **THEN** `exchange_code` raises `GoogleCalAuthError`

Tests: backend/tests/test_gcal_sync_service.py::TestExchangeCode::test_missing_refresh_token_is_hard_error

#### Scenario: id_token absent
- **WHEN** credentials carry no `id_token` and the calendar list has a primary calendar `me@gmail.com`
- **THEN** both the Google account id and the email are `me@gmail.com`

Tests: backend/tests/test_gcal_sync_service.py::TestExchangeCode::test_id_token_absent_falls_back_to_primary_calendar

#### Scenario: Exchange failure redirects
- **WHEN** the code exchange raises any exception
- **THEN** the callback redirects to `/settings/?google=error&reason=provider` instead of returning a 500

Tests: backend/tests/test_gcal_sync_views.py::TestCallback::test_provider_error_redirects

### Requirement: Account upsert on connect and reconnect
The system SHALL, after a successful exchange, upsert the account by `(user, google_account_id)` under a row lock, store email, encrypted refresh token, access token when present, expiry and `last_verified_at`, save with a full save and redirect to `/settings/?google=connected`.
Enforced: backend/gcal_sync/views.py::callback, backend/gcal_sync/models.py::GoogleCalendarAccount

#### Scenario: First connect
- **WHEN** the callback succeeds for Google account `sub-9`
- **THEN** it redirects to `google=connected` and the user's row for `sub-9` stores the email and the decryptable refresh token

Tests: backend/tests/test_gcal_sync_views.py::TestCallback::test_successful_callback_upserts

#### Scenario: Reconnect same Google account
- **WHEN** the same Google account reconnects with a new email and a rotated refresh token
- **THEN** exactly one row exists for that pair and it holds the new email and refresh token

Tests: backend/tests/test_gcal_sync_views.py::TestCallback::test_reconnect_same_account_updates_in_place

### Requirement: Connected account list
The system SHALL return `{"accounts": [...]}` with `id`, `email` and ISO `last_verified_at` (or null) for each of the caller's Google accounts, ordered by email then id, and never any token field.
Enforced: backend/gcal_sync/views.py::accounts, backend/gcal_sync/views.py::_accounts_payload

#### Scenario: Two connected accounts
- **WHEN** the user has accounts `a@gmail.com` and `b@gmail.com`
- **THEN** both emails are listed and no entry has a token field

Tests: backend/tests/test_gcal_sync_views.py::TestAccounts::test_list_accounts

### Requirement: Account disconnect
The system SHALL, on `DELETE /api/calendar/google/accounts/<id>/`, delete only a row owned by the caller, respond 200 even when nothing matched, and return the refreshed account list.
Enforced: backend/gcal_sync/views.py::account_detail

#### Scenario: Disconnect own account
- **WHEN** the user deletes their only account
- **THEN** the response is 200 with an empty `accounts` list and the row is gone

Tests: backend/tests/test_gcal_sync_views.py::TestAccounts::test_disconnect_own_account

#### Scenario: Another user's account id
- **WHEN** the user deletes an account id owned by another user
- **THEN** the response is 200 and the other user's row still exists

Tests: backend/tests/test_gcal_sync_views.py::TestAccounts::test_disconnect_scoped_to_user_idor

### Requirement: Token encryption at rest
The system SHALL store refresh and access tokens as Fernet ciphertext under `GOOGLE_OAUTH_TOKEN_KEY`, independent of other providers' keys, and raise `ImproperlyConfigured` on a missing or invalid key or undecryptable ciphertext.
Enforced: backend/gcal_sync/crypto.py::encrypt_token, backend/gcal_sync/crypto.py::decrypt_token, backend/gcal_sync/models.py::GoogleCalendarAccount

#### Scenario: Key rotated or missing
- **WHEN** a Google token is decrypted under a different key, or encrypted with an empty or invalid key
- **THEN** `ImproperlyConfigured` is raised without the plaintext in its message

Tests: backend/tests/test_integration_infrastructure.py::test_existing_fernet_ciphertext_and_key_failures

#### Scenario: Other provider's ciphertext
- **WHEN** ciphertext made with the CalDAV key is decrypted by the Google crypto helper under distinct keys
- **THEN** `ImproperlyConfigured` is raised

Tests: backend/tests/test_integration_infrastructure.py::test_provider_keys_remain_independent

### Requirement: Admin exposes no token material
The system SHALL register a read-only admin for Google accounts that shows user, account id, email and timestamps, never renders token ciphertext, and forbids add and change.
Enforced: backend/gcal_sync/admin.py::GoogleCalendarAccountAdmin

#### Scenario: Ops views an account in admin
- **WHEN** a staff user opens a Google account in Django admin
- **THEN** no token field is shown and the account cannot be added or edited there

### Requirement: Credentials are never logged
The system MUST NOT write OAuth codes, refresh or access tokens, or their ciphertext to logs during code exchange or event fetch.
Enforced: backend/gcal_sync/service.py::exchange_code, backend/gcal_sync/service.py::_normalize_gcal_event, backend/gcal_sync/service.py::build_authorization_url

#### Scenario: Fetch with a malformed event and an exchange
- **WHEN** an event fetch logs a malformed-event warning and a code exchange runs with DEBUG logging
- **THEN** no log message contains the code, either token or either ciphertext's hex

Tests: backend/tests/test_gcal_sync_service.py::TestCredentialsNeverLogged::test_tokens_never_appear_in_logs

### Requirement: Access token reuse and refresh
The system SHALL reuse the stored access token while its expiry is more than 60 seconds away, otherwise refresh with the refresh token, map a refresh error to `GoogleCalAuthError` and a transport error to `GoogleCalProviderError`, and copy the post-refresh `updated_at` onto the in-memory account.
Enforced: backend/gcal_sync/service.py::_ensure_access_token, backend/gcal_sync/service.py::_refresh_sync

#### Scenario: Fresh cached token
- **WHEN** the stored access token is valid for longer than the skew
- **THEN** it is returned without calling the token endpoint

Tests: backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_ensure_access_token_cache_reuse_skips_refresh

#### Scenario: Revoked grant
- **WHEN** the token refresh raises `RefreshError`
- **THEN** `GoogleCalAuthError` is raised

Tests: backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_refresh_sync_revoked_raises_auth

#### Scenario: Refresh rotates the cache version
- **WHEN** a refresh persists new tokens
- **THEN** the in-memory account's `updated_at` equals the persisted post-refresh value

Tests: backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_ensure_access_token_propagates_version_to_in_memory_account

### Requirement: Refreshed token persistence
The system SHALL persist refreshed tokens under a row lock with a full save, reuse the row's token without writing when it is already fresh and no rotated refresh token arrived, and always persist a refresh token Google returned that differs from the stored one.
Enforced: backend/gcal_sync/service.py::_persist_refreshed_tokens, backend/gcal_sync/service.py::_refresh_sync

#### Scenario: Expired row
- **WHEN** the row's access token is expired and a refresh result arrives
- **THEN** the new access token is stored, `updated_at` advances and the new version is returned

Tests: backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_persist_writes_when_expired

#### Scenario: Concurrent refresh already landed
- **WHEN** the row is already fresh and the caller has no rotated refresh token
- **THEN** the row's existing token is returned and `updated_at` does not change

Tests: backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_persist_skips_redundant_write_when_fresh_no_rotation

#### Scenario: Rotation detection
- **WHEN** a refresh returns a refresh token that differs from the input, or the same one
- **THEN** the rotated token is reported in the first case and `None` in the second, with an aware UTC expiry

Tests: backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_refresh_sync_detects_rotation, backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_refresh_sync_no_rotation_returns_none

#### Scenario: Rotated refresh token persisted
- **WHEN** a caller holds a rotated refresh token, even while the row is fresh
- **THEN** the rotated refresh token and new access token are stored and `updated_at` advances

Tests: backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_persist_rotated_refresh_even_when_fresh, backend/tests/test_gcal_sync_service.py::TestTokenLifecycle::test_concurrent_rotation_lost_update_guard

### Requirement: Per-account event fetch
The system SHALL fetch an account's events for the user's local day from calendars marked `selected`, querying each (URL-encoded id, `singleEvents=true`, `orderBy=startTime`, saved-zone day window, at most 8 at once) across pages, and raise `GoogleCalProviderError` past 100 pages.
Enforced: backend/gcal_sync/service.py::fetch_events_for_account, backend/gcal_sync/service.py::_fetch_selected_calendars, backend/gcal_sync/service.py::_fetch_events_for_calendar

#### Scenario: Only selected calendars
- **WHEN** an account has selected calendars and one unselected calendar
- **THEN** events from the unselected calendar are absent

Tests: backend/tests/test_gcal_sync_service.py::TestFetchEvents::test_multi_calendar_merge_and_normalisation

#### Scenario: Empty day
- **WHEN** no selected calendar has events in the window
- **THEN** the result is an empty list

Tests: backend/tests/test_gcal_sync_service.py::TestFetchEvents::test_empty_day_returns_empty

#### Scenario: Calendar id with reserved characters
- **WHEN** a calendar id contains `@` or `#`
- **THEN** the events request path carries them percent-encoded

Tests: backend/tests/test_gcal_sync_service.py::TestFetchEvents::test_calendar_id_is_url_encoded

#### Scenario: Pagination
- **WHEN** an events response carries `nextPageToken`, or pages never end
- **THEN** later pages are merged, and beyond 100 pages `GoogleCalProviderError` is raised

Tests: backend/tests/test_gcal_sync_service.py::TestPagination::test_events_pages_are_merged, backend/tests/test_gcal_sync_service.py::TestPagination::test_endless_pagination_raises_provider_error

### Requirement: Google event normalisation
The system SHALL skip cancelled or malformed events, convert timed events to UTC, map all-day dates to midnight in the saved zone with exclusive end, title missing summaries `(no title)`, set `external_uid` `<id>@google`, label with the account email, drop events outside the day and sort by start, title, uid.
Enforced: backend/gcal_sync/service.py::_normalize_gcal_event, backend/gcal_sync/service.py::fetch_events_for_account

#### Scenario: Timed and all-day events across calendars
- **WHEN** two selected calendars return a timed event and an all-day event
- **THEN** times are UTC, the all-day event is flagged and sorts first, every `account_label` is the account email and every `external_uid` ends with `@google`

Tests: backend/tests/test_gcal_sync_service.py::TestFetchEvents::test_multi_calendar_merge_and_normalisation

#### Scenario: Cancelled instance
- **WHEN** a calendar returns a cancelled event alongside a confirmed one
- **THEN** only the confirmed event is returned

Tests: backend/tests/test_gcal_sync_service.py::TestFetchEvents::test_cancelled_event_skipped

#### Scenario: All-day event in UTC
- **WHEN** an all-day event for 2026-05-07 (end date 2026-05-08) is fetched with the default UTC zone
- **THEN** it spans 2026-05-07T00:00Z to 2026-05-08T00:00Z and is flagged all-day

Tests: backend/tests/test_gcal_sync_service.py::TestNormalisationEdgeCases::test_all_day_event_utc_window

#### Scenario: All-day event in America/New_York
- **WHEN** the same all-day event is fetched with saved zone `America/New_York`
- **THEN** it spans 2026-05-07T04:00Z to 2026-05-08T04:00Z with `start_date` 2026-05-07 and `end_date` 2026-05-08

Tests: backend/tests/test_gcal_sync_service.py::TestNormalisationEdgeCases::test_all_day_event_non_utc_timezone

#### Scenario: Local-day window
- **WHEN** an event falls in the saved zone's local day but on another UTC date, or lies outside the window
- **THEN** the first is kept and the second is dropped

Tests: backend/tests/test_gcal_sync_service.py::TestNormalisationEdgeCases::test_cross_utc_midnight_event_is_in_qatar_local_day, backend/tests/test_gcal_sync_service.py::TestNormalisationEdgeCases::test_out_of_window_event_dropped

### Requirement: Provider error mapping
The system SHALL map a Google request timeout to `GoogleCalTimeoutError`, HTTP 401 or 403 to `GoogleCalAuthError` and any other non-2xx or transport error to `GoogleCalProviderError`, while letting `ImproperlyConfigured` propagate unwrapped.
Enforced: backend/gcal_sync/service.py::fetch_events_for_account, backend/gcal_sync/service.py::_raise_for_rest_status

#### Scenario: Timeout
- **WHEN** a Google request times out
- **THEN** `GoogleCalTimeoutError` is raised

Tests: backend/tests/test_gcal_sync_service.py::TestFetchEvents::test_timeout_maps_to_timeout_error

#### Scenario: Server error
- **WHEN** Google answers 500
- **THEN** `GoogleCalProviderError` is raised

Tests: backend/tests/test_gcal_sync_service.py::TestFetchEvents::test_provider_500_maps_to_provider_error

#### Scenario: Revoked access
- **WHEN** Google answers 401
- **THEN** `GoogleCalAuthError` is raised

Tests: backend/tests/test_gcal_sync_service.py::TestFetchEvents::test_revoked_401_maps_to_auth_error

### Requirement: Events request validation
The system SHALL answer `GET /api/calendar/google/events/<date>/` with 400 `Invalid date format. Use YYYY-MM-DD.` for a non-ISO date, and with 503, code `integration_account_missing` and meta `disconnected`/`unavailable` when the user has no Google account.
Enforced: backend/gcal_sync/views.py::events

#### Scenario: Malformed date
- **WHEN** the date segment is `not-a-date`
- **THEN** the response is 400

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_invalid_date_returns_400

#### Scenario: Parsed date passed downstream
- **WHEN** the date segment is `2026-05-07`
- **THEN** the service receives a `datetime.date` for 2026-05-07

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_parsed_date_contract

#### Scenario: No connected account
- **WHEN** the user has no Google account
- **THEN** the response is 503 with code `integration_account_missing` and meta `{"account_state": "disconnected", "resource_state": "unavailable"}`

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_no_accounts_returns_503, backend/tests/test_integration_infrastructure.py::test_missing_account_is_explicit_resource_state

### Requirement: Multi-account merge with per-account errors
The system SHALL fetch all accounts concurrently and return 200 with `events` sorted by start, title, uid, an always-present `account_errors` (`reconnect_required` for auth failures, `unavailable` otherwise) and meta `connected` with `ready` if any account succeeded.
Enforced: backend/gcal_sync/views.py::events

#### Scenario: Two healthy accounts
- **WHEN** two accounts each return one event
- **THEN** both events are returned and `account_errors` is empty

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_multi_account_merge

#### Scenario: One revoked account
- **WHEN** one account succeeds and another raises `GoogleCalAuthError`
- **THEN** the response is 200 with the healthy events and one `reconnect_required` error naming the failing email

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_partial_success, backend/tests/test_gcal_sync_views.py::TestEvents::test_mixed_cache_hit_and_per_account_auth_failure

#### Scenario: Provider or timeout failure
- **WHEN** an account fails with a provider error or a timeout
- **THEN** the response is 200 and its error is `unavailable`

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_provider_failure_is_unavailable, backend/tests/test_gcal_sync_views.py::TestEvents::test_timeout_failure_is_unavailable

#### Scenario: Every account failed
- **WHEN** all accounts fail
- **THEN** the response stays 200 with empty `events`, and `resource_state` is `provider_error` if any error is `unavailable`, otherwise `credentials_error`

### Requirement: Misconfigured token key returns 500
The system SHALL answer the events request with 500, detail `Google Calendar service is misconfigured. Contact the administrator.`, code `integration_configuration_error` and meta `configuration_error`/`unavailable` when any account fetch raises `ImproperlyConfigured`.
Enforced: backend/gcal_sync/views.py::events

#### Scenario: Stored token cannot be decrypted
- **WHEN** an account fetch raises `ImproperlyConfigured`
- **THEN** the whole response is 500 and its detail mentions `misconfigured`

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_improperly_configured_returns_500

### Requirement: Versioned Google event cache
The system SHALL cache each account's successful event list for `GOOGLE_CACHE_TTL_SECONDS` under `gcal_events:v2:{user}:{account}:{updated_at}:{date}:{zone}`, serve hits without a provider call, never cache failures, and run cache I/O off the event loop.
Enforced: backend/gcal_sync/cache.py::events_cache_key, backend/gcal_sync/cache.py::get_cached_events, backend/gcal_sync/cache.py::set_cached_events, backend/gcal_sync/views.py::events

#### Scenario: Key shape
- **WHEN** the key is computed for user 7, account 11, a given `updated_at`, 2026-05-07 and `Asia/Qatar`
- **THEN** it is `gcal_events:v2:7:11:<updated_at ISO>:2026-05-07:Asia/Qatar`

Tests: backend/tests/test_integration_infrastructure.py::test_cache_keys_preserve_provider_identity_and_filter_scope

#### Scenario: Cache hit
- **WHEN** an account's events for the date and zone are cached
- **THEN** they are returned and the provider fetch is not called

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_cache_hit_short_circuits, backend/tests/test_gcal_sync_views.py::TestEvents::test_without_refresh_cached_account_not_refetched

#### Scenario: Saved zone changes
- **WHEN** the user's saved time zone changes between two requests for the same date
- **THEN** the second request misses the cache and fetches with the new zone

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_timezone_change_misses_old_cache

#### Scenario: Cache I/O thread
- **WHEN** the async cache helpers read or write
- **THEN** the cache backend is called outside the event-loop thread

Tests: backend/tests/test_integration_infrastructure.py::test_google_cache_io_runs_outside_the_event_loop

### Requirement: Forced refresh bypasses the cache
The system SHALL, only when the `refresh` query value is exactly `1`, fetch every connected account live instead of reading the cache, and re-warm the cache with each successful result.
Enforced: backend/gcal_sync/views.py::events

#### Scenario: refresh=1
- **WHEN** one of two accounts has a cached entry and the request has `?refresh=1`
- **THEN** both accounts are fetched, both results are cached, and the next plain request makes no provider call

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_refresh_bypasses_all_accounts_and_rewarms

#### Scenario: Other refresh values
- **WHEN** `refresh` is `0`, `true`, `yes` or empty
- **THEN** the cached account is served from cache and only the uncached account is fetched

Tests: backend/tests/test_gcal_sync_views.py::TestEvents::test_non_one_refresh_value_does_not_bypass_cache

### Requirement: Production OAuth configuration check
The system SHALL, when `DEBUG=False`, emit `gcal_sync.E001` for each unset `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` or `GOOGLE_OAUTH_REDIRECT_URI`, and for a missing or non-Fernet `GOOGLE_OAUTH_TOKEN_KEY`, regardless of whether any account exists.
Enforced: backend/gcal_sync/checks.py::error_google_oauth_config_missing_in_production

#### Scenario: Fully configured or debug
- **WHEN** all four values are valid, or `DEBUG=True` with all empty
- **THEN** no error is emitted

Tests: backend/tests/test_gcal_sync_checks.py::TestE001ConfigMissing::test_silent_when_fully_configured, backend/tests/test_gcal_sync_checks.py::TestE001ConfigMissing::test_silent_in_debug

#### Scenario: Missing or malformed token key
- **WHEN** `GOOGLE_OAUTH_TOKEN_KEY` is empty or not a valid Fernet key
- **THEN** `gcal_sync.E001` names the key, or says it is not a valid Fernet key

Tests: backend/tests/test_gcal_sync_checks.py::TestE001ConfigMissing::test_fires_when_token_key_missing, backend/tests/test_gcal_sync_checks.py::TestE001ConfigMissing::test_fires_when_token_key_malformed

#### Scenario: Missing client variable with no accounts
- **WHEN** any one client variable is empty, even with no Google account in the database
- **THEN** `gcal_sync.E001` names that variable

Tests: backend/tests/test_gcal_sync_checks.py::TestE001ConfigMissing::test_fires_when_any_client_var_missing, backend/tests/test_gcal_sync_checks.py::TestE001ConfigMissing::test_fires_even_with_no_accounts

### Requirement: Non-shared cache warning
The system SHALL emit warning `gcal_sync.W001` when `DEBUG=False`, the default cache is LocMem, FileBased or Dummy and at least one Google account exists, and stay silent when the account table is absent.
Enforced: backend/gcal_sync/checks.py::warn_ineffective_cache_with_gcal_sync

#### Scenario: Ineffective backend with an account
- **WHEN** an account exists and the backend is LocMem, FileBased or Dummy in production
- **THEN** one `gcal_sync.W001` warning is returned

Tests: backend/tests/test_gcal_sync_checks.py::TestW001IneffectiveCache::test_fires_with_locmem_and_account, backend/tests/test_gcal_sync_checks.py::TestW001IneffectiveCache::test_fires_with_each_ineffective_backend

#### Scenario: Silent cases
- **WHEN** no account exists, the backend is Redis, `DEBUG=True`, or the table query fails during first migrate
- **THEN** no warning is returned

Tests: backend/tests/test_gcal_sync_checks.py::TestW001IneffectiveCache::test_silent_with_no_account, backend/tests/test_gcal_sync_checks.py::TestW001IneffectiveCache::test_silent_with_shared_cache, backend/tests/test_gcal_sync_checks.py::TestW001IneffectiveCache::test_silent_when_debug, backend/tests/test_gcal_sync_checks.py::TestW001IneffectiveCache::test_swallows_db_error_during_first_migrate

### Requirement: Google numeric settings validation
The system SHALL refuse to load settings when `GOOGLE_CACHE_TTL_SECONDS` or `GOOGLE_REQUEST_TIMEOUT` is zero or negative, raising `ValueError`.
Enforced: backend/day_forge/settings.py::GOOGLE_CACHE_TTL_SECONDS, backend/day_forge/settings.py::GOOGLE_REQUEST_TIMEOUT

#### Scenario: Non-positive timeout
- **WHEN** `GOOGLE_REQUEST_TIMEOUT=0` is set in the environment
- **THEN** importing settings raises `ValueError`
