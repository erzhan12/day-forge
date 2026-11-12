# integrations/caldav Specification

## Purpose
The `calendar_sync` app gives each user a read-only Apple Calendar (iCloud CalDAV) connection. This spec covers connecting, verifying and disconnecting the account, encrypting the app-specific password at rest, fetching one local day of events with a versioned cache, the error and resource-state envelopes, the startup checks and settings, and the per-user travel-time rule CRUD that `calendar_sync` also owns. Importing an event as a block belongs to `schedules/blocks`; this spec states only the privacy guarantee that event text stays out of AI prompts, whose detailed redaction rules live in the AI specs.

## Requirements

### Requirement: Account status never exposes the password
The system SHALL answer `GET /api/calendar/account/` with `connected`, `apple_id`, `base_url`, `last_verified_at` and `default_base_url` (from `CALDAV_DEFAULT_BASE_URL`), using nulls for the account fields when no account exists. No response field SHALL carry the password or its ciphertext.
Enforced: backend/calendar_sync/views.py::_account_status_payload, backend/calendar_sync/views.py::account

#### Scenario: No account
- **WHEN** a user without a CalDAV account requests the status
- **THEN** the response has `connected: false`, null account fields and the configured `default_base_url`

Tests: backend/tests/test_calendar_sync_views.py::TestAccountGet::test_returns_disconnected_status_with_default_base_url

#### Scenario: Connected account
- **WHEN** a user with a stored account requests the status
- **THEN** the response has `connected: true` with the Apple ID, base URL and last verification time, and no password field

Tests: backend/tests/test_calendar_sync_views.py::TestAccountGet::test_returns_connected_status_when_account_present

### Requirement: Connect body validation
The system SHALL reject a `POST /api/calendar/account/` body with 400 and per-field errors plus `errors.detail` when `apple_id` is missing or not an email, `password` is missing, empty or over 128 characters, or a non-empty `base_url` is not an http(s) URL. An empty or blank `base_url` SHALL fall back to `CALDAV_DEFAULT_BASE_URL`.
Enforced: backend/calendar_sync/schemas.py::validate_account_payload, backend/calendar_sync/views.py::account

#### Scenario: Missing fields
- **WHEN** the body omits `apple_id` and `password`
- **THEN** the response is 400 with the error envelope and nothing is stored

Tests: backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_missing_fields_returns_400_envelope

#### Scenario: Malformed field values
- **WHEN** `apple_id` is not an email, `base_url` is not an http(s) URL, or `password` exceeds 128 characters
- **THEN** the response is 400 with the error keyed by that field

Tests: backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_malformed_apple_id_returns_400_per_field, backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_malformed_base_url_returns_400_per_field, backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_password_too_long_returns_400_per_field

#### Scenario: Empty base URL
- **WHEN** `base_url` is an empty string
- **THEN** the account is verified and stored with the default base URL

Tests: backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_empty_base_url_falls_back_to_default

### Requirement: Connect verifies before it stores
The system SHALL verify credentials against the CalDAV server, by loading the principal and listing its calendars, before writing anything. On success it SHALL upsert the user's single account under a row lock, encrypt the password, set `last_verified_at` and save so `updated_at` advances, and return the status payload.
Enforced: backend/calendar_sync/views.py::account, backend/calendar_sync/service.py::verify_credentials

#### Scenario: Valid credentials
- **WHEN** the server accepts the credentials
- **THEN** the account is stored with an encrypted password and the response shows `connected: true`

Tests: backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_persists_encrypted_password

#### Scenario: Rejected credentials
- **WHEN** the server rejects the credentials
- **THEN** the response is 401 with `code: integration_credentials_error` and no account row is written

Tests: backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_invalid_credentials_does_not_persist, backend/tests/test_integration_infrastructure.py::test_failed_account_verification_is_not_session_expiry

### Requirement: Connect failures map to resource errors
The system SHALL map a failed verification to 401 (credentials rejected), 504 (timeout) or 502 (other DAV failure), each with the resource-error envelope. Its `meta.account_state` SHALL be `connected` if the user already had an account and `disconnected` otherwise. Error bodies MUST NOT echo the provider's error text.
Enforced: backend/calendar_sync/views.py::_service_error_response, backend/calendar_sync/service.py::verify_credentials, backend/common/integration_response.py::resource_error

#### Scenario: Timeout during connect
- **WHEN** verification times out
- **THEN** the response is 504 with the error envelope

Tests: backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_timeout_returns_504_envelope

#### Scenario: Provider failure during connect
- **WHEN** verification raises a DAV error other than an authorization error
- **THEN** the response is 502 with the error envelope

Tests: backend/tests/test_calendar_sync_views.py::TestAccountPost::test_post_provider_failure_returns_502_envelope

#### Scenario: First connect with bad credentials
- **WHEN** a user with no account submits rejected credentials
- **THEN** `meta` is `{account_state: disconnected, resource_state: credentials_error}` and the provider message is absent from the body

Tests: backend/tests/test_integration_infrastructure.py::test_failed_account_verification_is_not_session_expiry

### Requirement: Connect rate limit
The system SHALL count each valid connect POST against a per-user fixed one-hour window keyed `connect_rl:caldav:<user_id>` with budget `CALDAV_CONNECT_RATE_LIMIT_PER_HOUR` (default 20). Over budget it SHALL return 429 with `Retry-After` before verifying. Failed verifications count; invalid bodies, GET and DELETE do not.
Enforced: backend/calendar_sync/views.py::account, backend/schedules/ratelimit.py::consume_rate_limit, backend/schedules/ratelimit.py::rate_limited_response

#### Scenario: Budget exhausted
- **WHEN** a user exceeds the hourly budget
- **THEN** the response is 429 with a rate-limit message and the server is not contacted

Tests: backend/tests/test_calendar_sync_views.py::TestConnectRateLimit, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_returns_429_once_connect_budget_exceeded, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_429_short_circuits_before_verify_credentials, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_counter_stored_under_expected_key

#### Scenario: What counts
- **WHEN** a verification fails, a body fails validation, or the user sends GET or DELETE
- **THEN** only the failed verification consumes a token

Tests: backend/tests/test_calendar_sync_views.py::TestConnectRateLimit, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_failed_verify_still_consumes_token, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_pre_validation_does_not_consume_token, backend/tests/_connect_rate_limit_contract.py::ConnectRateLimitContract::test_get_and_delete_not_rate_limited

### Requirement: Idempotent disconnect
The system SHALL handle `DELETE /api/calendar/account/` by deleting the user's account if present and returning the disconnected status payload either way. Cached events for that account SHALL become unreachable without explicit cache deletion.
Enforced: backend/calendar_sync/views.py::account

#### Scenario: Delete existing account
- **WHEN** a connected user disconnects
- **THEN** the row is removed and the response matches a disconnected status

Tests: backend/tests/test_calendar_sync_views.py::TestAccountDelete::test_delete_removes_row

#### Scenario: Delete without an account
- **WHEN** a user with no account disconnects
- **THEN** the response is 200 with the disconnected status

Tests: backend/tests/test_calendar_sync_views.py::TestAccountDelete::test_delete_is_idempotent

#### Scenario: Events after disconnect
- **WHEN** a user disconnects and then requests a previously cached day
- **THEN** the response is 503, not the cached events

Tests: backend/tests/test_calendar_sync_views.py::TestCacheInvalidation::test_cache_invalidates_on_account_delete

### Requirement: Endpoints require login and CSRF
The system SHALL require an authenticated session for every CalDAV and travel-rule endpoint and SHALL enforce CSRF on account POST and DELETE.
Enforced: backend/calendar_sync/views.py::account, backend/calendar_sync/views.py::events

#### Scenario: Anonymous request
- **WHEN** an anonymous client requests account status or events
- **THEN** it does not receive account or event data

Tests: backend/tests/test_calendar_sync_views.py::TestAuthGuard::test_anonymous_account_get_redirects_to_login, backend/tests/test_calendar_sync_views.py::TestAuthGuard::test_anonymous_events_redirects_to_login

#### Scenario: Missing CSRF token
- **WHEN** a logged-in client posts or deletes the account without a CSRF token
- **THEN** the response is 403

Tests: backend/tests/test_calendar_sync_views.py::TestCsrfGuard::test_post_without_csrf_token_returns_403, backend/tests/test_calendar_sync_views.py::TestCsrfGuard::test_delete_without_csrf_token_returns_403

### Requirement: Password encrypted at rest with its own key
The system SHALL store the password only as Fernet ciphertext under `CALDAV_ENCRYPTION_KEY`, independent of other providers' keys. A missing or invalid key, or undecryptable ciphertext, SHALL raise `ImproperlyConfigured` naming the setting but never the secret.
Enforced: backend/calendar_sync/crypto.py::encrypt_password, backend/calendar_sync/crypto.py::decrypt_password, backend/common/integration_crypto.py::decrypt_secret

#### Scenario: Key rotated
- **WHEN** a stored password was written with an older key
- **THEN** decryption raises `ImproperlyConfigured` naming the setting but not the secret

Tests: backend/tests/test_integration_infrastructure.py::test_existing_fernet_ciphertext_and_key_failures

#### Scenario: Another provider's key
- **WHEN** CalDAV ciphertext is decrypted with the Google, Todoist or Habitica helper
- **THEN** decryption fails

Tests: backend/tests/test_integration_infrastructure.py::test_provider_keys_remain_independent

### Requirement: Password decrypted only at the service boundary
The system SHALL decrypt the stored password only inside the event fetch service and MUST NOT write it to logs. Views pass the account object and never read the plaintext. The admin SHALL show accounts read-only, without the ciphertext field and with no add or change permission.
Enforced: backend/calendar_sync/service.py::fetch_events_for_date, backend/calendar_sync/models.py::CalDAVAccount.get_password, backend/calendar_sync/admin.py::CalDAVAccountAdmin

#### Scenario: Fetch with logging enabled
- **WHEN** events are fetched while all log output is captured
- **THEN** the password does not appear in any log record

Tests: backend/tests/test_calendar_sync_service.py::TestCredentialsNeverLogged::test_password_never_appears_in_logs

### Requirement: Events request validation
The system SHALL return 400 from `GET /api/calendar/events/<date>/` when the date segment is not an ISO date that `date.fromisoformat` parses. When the user has no CalDAV account it SHALL return 503 with `code: integration_account_missing` and `meta` `{account_state: disconnected, resource_state: unavailable}`.
Enforced: backend/calendar_sync/views.py::events

#### Scenario: Invalid date
- **WHEN** the date segment is not a parseable ISO date
- **THEN** the response is 400 with `Invalid date format. Use YYYY-MM-DD.`

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_400_on_invalid_date

#### Scenario: No account
- **WHEN** a user without an account requests events
- **THEN** the response is 503 with the account-missing code and metadata

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_503_when_no_account, backend/tests/test_integration_infrastructure.py::test_missing_account_is_explicit_resource_state

### Requirement: Events cover the user's local day
The system SHALL query every calendar for the UTC span between local midnights of the date and the next date in the user's saved time zone, so DST days are 23 or 25 hours. It SHALL expand recurrences, keep events overlapping that span, and return them sorted by start, title and UID with `meta` `{connected, ready}`.
Enforced: backend/calendar_sync/service.py::fetch_events_for_date, backend/calendar_sync/time.py::local_day_bounds_utc, backend/calendar_sync/views.py::events

#### Scenario: Successful fetch
- **WHEN** the account has timed and all-day events on the date
- **THEN** the response lists them with `meta.account_state` `connected` and `meta.resource_state` `ready`

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_fetch_success, backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_fetch_success_normalises_timed_and_allday

#### Scenario: DST transition day
- **WHEN** the date is a daylight-saving change in the user's zone
- **THEN** the query window runs from that local midnight to the next one

Tests: backend/tests/test_calendar_time.py::test_local_day_bounds_cover_entire_day

#### Scenario: Event across UTC midnight
- **WHEN** an event lies inside the user's local day but spans UTC midnight
- **THEN** it is included for that local date

Tests: backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_cross_utc_midnight_event_is_in_qatar_local_day, backend/tests/test_calendar_time.py::test_cross_midnight_event_overlaps_local_day

#### Scenario: Recurring event
- **WHEN** a recurring event has an occurrence on the date
- **THEN** that single occurrence is returned with the recurrence ID appended to its `external_uid`

Tests: backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_recurring_event_expansion_single_day

#### Scenario: Empty day
- **WHEN** no calendar has events on the date
- **THEN** an empty list is returned

Tests: backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_fetch_empty_day_returns_empty_list

### Requirement: Event normalization
The system SHALL return each event with `title`, UTC `start`/`end`, `calendar_name`, `all_day`, `external_uid`, `account_label` (`""` for CalDAV) and, for all-day events only, `start_date` and exclusive `end_date`. Floating times use the saved zone; a missing end uses `DURATION` or the RFC 5545 default.
Enforced: backend/calendar_sync/service.py::_normalize_vevent, backend/calendar_sync/schemas.py::normalized_event_to_dict

#### Scenario: Missing DTEND
- **WHEN** an event has `DURATION` but no `DTEND`, or neither
- **THEN** the end is start plus duration, or one day for all-day and zero length for timed events

Tests: backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_vevent_with_duration_but_no_dtend, backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_vevent_without_dtend_or_duration_uses_rfc5545_default

#### Scenario: Floating time
- **WHEN** an event time has no time zone, including a repeated DST hour
- **THEN** it is read as wall time in the user's saved zone, first occurrence for the repeated hour

Tests: backend/tests/test_calendar_time.py::test_naive_caldav_time_uses_saved_timezone, backend/tests/test_calendar_time.py::test_repeated_floating_hour_uses_first_occurrence_without_fold

#### Scenario: All-day event
- **WHEN** an all-day event's local midnight falls on a different UTC date
- **THEN** `start_date` and `end_date` keep the original calendar dates

Tests: backend/tests/test_calendar_time.py::test_all_day_date_stays_on_its_calendar_day_across_utc_midnight

### Requirement: Malformed events are skipped
The system SHALL skip, with a warning log, a single event whose iCalendar data cannot be parsed, expanded or normalized, and SHALL still return the day's other events.
Enforced: backend/calendar_sync/service.py::_expand_events, backend/calendar_sync/service.py::_normalize_vevent

#### Scenario: Broken VEVENT
- **WHEN** one event lacks a usable `DTSTART`
- **THEN** it is dropped and a warning is logged instead of failing the fetch

Tests: backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_malformed_vevent_is_skipped_not_crash

### Requirement: Fetch failures map to resource errors
The system SHALL fail the whole fetch, never returning a partial day, when any calendar fails: 401 `credentials_error`, 504 `unavailable` or 502 `provider_error`, each with a stable `code` and `meta.account_state` `connected`.
Enforced: backend/calendar_sync/service.py::fetch_events_for_date, backend/calendar_sync/views.py::_service_error_response

#### Scenario: Stored credentials rejected
- **WHEN** the server rejects the stored credentials
- **THEN** the response is 401 with `code: integration_credentials_error`

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_auth_error_returns_401_envelope, backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_fetch_invalid_credentials_raises_auth, backend/tests/test_integration_infrastructure.py::test_resource_failure_preserves_account_state

#### Scenario: Timeout
- **WHEN** the CalDAV call exceeds `CALDAV_REQUEST_TIMEOUT`
- **THEN** the response is 504 with `code: integration_unavailable`

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_timeout_returns_504_envelope, backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_fetch_timeout_raises_timeout

#### Scenario: One calendar fails
- **WHEN** the search on one of several calendars raises a DAV error
- **THEN** the response is 502 with `code: integration_provider_error` and no events

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_per_calendar_dav_error_returns_502_envelope, backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_provider_failure_returns_502_envelope, backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_fetch_per_calendar_dav_error_propagates, backend/tests/test_calendar_sync_service.py::TestFetchEventsForDate::test_fetch_provider_failure_raises_provider

### Requirement: Encryption misconfiguration is a config-shaped 500
The system SHALL answer an `ImproperlyConfigured` encryption failure, during a connect save or an events fetch, with 500 `Calendar service is misconfigured. Contact the administrator.`, `code: integration_configuration_error` and `meta.account_state` `configuration_error`, never a 502.
Enforced: backend/calendar_sync/views.py::events, backend/calendar_sync/views.py::account

#### Scenario: Key cannot decrypt the stored password
- **WHEN** the stored ciphertext no longer matches `CALDAV_ENCRYPTION_KEY`
- **THEN** the events response is 500 with the configuration message

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_decryption_misconfig_returns_500_with_config_message

#### Scenario: Key missing when connecting
- **WHEN** credentials verify but the password cannot be encrypted because the key is missing or invalid
- **THEN** the connect response is 500 with the configuration message and nothing is written

### Requirement: Versioned event cache
The system SHALL cache each successful day under `caldav_events:v2:<user_id>:<updated_at ISO>:<date>:<time zone>` for `CALDAV_CACHE_TTL_SECONDS` (default 300). Saving the account or changing the saved zone changes the key, so old entries are never served.
Enforced: backend/calendar_sync/cache.py::events_cache_key, backend/common/integration_cache.py::versioned_key, backend/calendar_sync/views.py::events

#### Scenario: Second read
- **WHEN** the same day is requested twice without changes
- **THEN** the second response comes from cache without contacting the server

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_cache_hit_short_circuits_second_call, backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_cache_hit_without_refresh_skips_service

#### Scenario: Account updated or zone changed
- **WHEN** the account is re-saved or the user's saved time zone changes
- **THEN** the next read misses the cache and fetches again

Tests: backend/tests/test_calendar_sync_views.py::TestCacheInvalidation::test_cache_invalidates_on_account_update, backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_timezone_change_misses_old_cache, backend/tests/test_calendar_time.py::test_calendar_caches_separate_timezones_and_old_key_namespace

#### Scenario: Key shape
- **WHEN** the key is built for a user, account version, date and zone
- **THEN** it equals the `caldav_events:v2` key with those parts in that order

Tests: backend/tests/test_integration_infrastructure.py::test_cache_keys_preserve_provider_identity_and_filter_scope

### Requirement: Forced refresh
The system SHALL bypass the cache read only when the query has `refresh=1`, fetch live, and store the result back in the cache. Any other `refresh` value SHALL behave as a normal read.
Enforced: backend/calendar_sync/views.py::events

#### Scenario: refresh=1
- **WHEN** a cached day is requested with `?refresh=1`
- **THEN** the server is contacted and the new result replaces the cache entry

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_refresh_bypasses_cache_and_rewarms

#### Scenario: Other refresh values
- **WHEN** `refresh` is any value other than `1`
- **THEN** the cached events are returned

Tests: backend/tests/test_calendar_sync_views.py::TestEventsEndpoint::test_non_one_refresh_value_does_not_bypass_cache

### Requirement: Startup checks for production
The system SHALL report `calendar_sync.E001` when `DEBUG` is false and `CALDAV_ENCRYPTION_KEY` is unset or not a valid Fernet key, and warn `calendar_sync.W001` when `DEBUG` is false, an account exists and the default cache is LocMem, FileBased or Dummy. W001 MUST tolerate a missing table.
Enforced: backend/calendar_sync/checks.py::error_caldav_encryption_key_missing_in_production, backend/calendar_sync/checks.py::warn_ineffective_cache_with_calendar_sync

#### Scenario: Missing or malformed key in production
- **WHEN** `DEBUG=False` and the key is empty or malformed
- **THEN** E001 is reported; with `DEBUG=True` or a valid key it is not

Tests: backend/tests/test_calendar_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_fires_when_key_missing_in_prod, backend/tests/test_calendar_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_fires_when_key_is_malformed_in_prod, backend/tests/test_calendar_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_silent_when_debug_true, backend/tests/test_calendar_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_silent_when_key_set_in_prod, backend/tests/test_calendar_sync_checks.py::TestE001EncryptionKeyMissing::test_e001_silent_when_malformed_key_in_debug

#### Scenario: Non-shared cache with accounts
- **WHEN** `DEBUG=False`, an ineffective backend is configured and an account exists
- **THEN** W001 is reported; with no account, a shared backend, `DEBUG=True` or a missing table it is not

Tests: backend/tests/test_calendar_sync_checks.py::TestW001IneffectiveCache::test_w001_fires_with_locmem_and_account, backend/tests/test_calendar_sync_checks.py::TestW001IneffectiveCache::test_w001_fires_with_each_ineffective_backend, backend/tests/test_calendar_sync_checks.py::TestW001IneffectiveCache::test_w001_silent_with_no_account, backend/tests/test_calendar_sync_checks.py::TestW001IneffectiveCache::test_w001_silent_with_shared_cache, backend/tests/test_calendar_sync_checks.py::TestW001IneffectiveCache::test_w001_silent_when_debug_true, backend/tests/test_calendar_sync_checks.py::TestW001IneffectiveCache::test_w001_swallows_db_error_during_first_migrate

### Requirement: CalDAV settings validated at import
The system SHALL read `CALDAV_DEFAULT_BASE_URL` (default `https://caldav.icloud.com/`), `CALDAV_REQUEST_TIMEOUT` (10 s), `CALDAV_CACHE_TTL_SECONDS` (300) and `CALDAV_CONNECT_RATE_LIMIT_PER_HOUR` (20), and MUST raise `ValueError` at settings import when the timeout, TTL or rate limit is not positive.
Enforced: backend/day_forge/settings.py::CALDAV_CONNECT_RATE_LIMIT_PER_HOUR, backend/day_forge/settings.py::CALDAV_CACHE_TTL_SECONDS, backend/day_forge/settings.py::CALDAV_REQUEST_TIMEOUT

#### Scenario: Non-positive connect budget
- **WHEN** `CALDAV_CONNECT_RATE_LIMIT_PER_HOUR` is 0 or negative
- **THEN** settings import fails with `ValueError`; when unset the budget is 20

Tests: backend/tests/test_settings_validation.py::test_non_positive_connect_rate_limit_raises_at_import, backend/tests/test_settings_validation.py::test_connect_rate_limit_default_is_twenty

#### Scenario: Non-positive timeout or TTL
- **WHEN** `CALDAV_REQUEST_TIMEOUT` or `CALDAV_CACHE_TTL_SECONDS` is 0 or negative
- **THEN** settings import fails with `ValueError`

### Requirement: Travel rules are user-scoped
The system SHALL list only the requesting user's travel rules at `GET /api/calendar/travel-rules/`, ordered by `order` then `id`, as `id`, `keyword`, `calendar_name`, `travel_there_minutes`, `travel_back_minutes`, `category` and `order`. PATCH or DELETE of another user's rule SHALL return 404.
Enforced: backend/calendar_sync/travel_rules.py::travel_rules_collection, backend/calendar_sync/travel_rules.py::travel_rule_detail, backend/calendar_sync/travel_rules.py::serialize_travel_rule

#### Scenario: Listing
- **WHEN** two users each have rules
- **THEN** each sees only their own, in ascending order

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_list_scoped_to_user, backend/tests/test_from_event.py::TestTravelRuleCrud::test_create_and_list_ordering

#### Scenario: Cross-user id
- **WHEN** a user patches or deletes another user's rule id
- **THEN** the response is 404

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_cross_user_pk_returns_404

#### Scenario: Anonymous
- **WHEN** an anonymous client lists or creates rules
- **THEN** it is redirected to login

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_unauthenticated_redirects, backend/tests/test_from_event.py::TestTravelRuleCrud::test_unauthenticated_create_redirects

### Requirement: Travel rule field validation
The system SHALL trim `keyword` (max 100) and `calendar_name` (max 200), require at least one non-empty after a create or merged PATCH (400 `errors.match_constraints`), accept minutes 0-600 and `order` within ±1,000,000 as plain integers, and `category` as `""` or a slug in the user's catalog.
Enforced: backend/calendar_sync/travel_rules.py::_parse_create_payload, backend/calendar_sync/travel_rules.py::_parse_patch_payload, backend/calendar_sync/models.py::TravelRule.clean

#### Scenario: No match constraint
- **WHEN** a create has neither keyword nor calendar name, or a PATCH would blank both
- **THEN** the response is 400 under `match_constraints`

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_create_requires_keyword_or_calendar_name, backend/tests/test_from_event.py::TestTravelRuleCrud::test_patch_rejects_blanking_both_match_constraints, backend/tests/test_from_event.py::TestTravelRuleCrud::test_patch_rejects_blanking_calendar_only_rule, backend/tests/test_from_event.py::TestTravelRuleCrud::test_model_clean_rejects_both_blank_match_constraints

#### Scenario: Either constraint alone
- **WHEN** a rule has only a keyword or only a calendar name
- **THEN** it is accepted

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_create_calendar_only_without_keyword_key, backend/tests/test_from_event.py::TestTravelRuleCrud::test_create_keyword_only_without_calendar_name_key, backend/tests/test_from_event.py::TestTravelRuleCrud::test_patch_can_blank_keyword_when_calendar_name_remains, backend/tests/test_from_event.py::TestTravelRuleCrud::test_patch_allows_blank_calendar_name_when_keyword_remains, backend/tests/test_from_event.py::TestTravelRuleCrud::test_model_clean_allows_calendar_only_rule

#### Scenario: Invalid values
- **WHEN** minutes exceed 600, a category is not in the catalog, or a calendar name is not a string or too long
- **THEN** the response is 400 keyed by that field

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_create_validation_rejected, backend/tests/test_from_event.py::TestTravelRuleCrud::test_create_rejects_invalid_calendar_name, backend/tests/test_from_event.py::TestTravelRuleCrud::test_patch_rejects_invalid_calendar_name

### Requirement: Travel rule create, update and delete
The system SHALL create a rule with 201, defaulting minutes to 0, `category` to `""` and an omitted `order` to the user's max plus one (capped at 1,000,000). It SHALL refuse creation once the user has 100 rules. PATCH needs at least one editable field and returns the rule; DELETE returns `{"ok": true}`.
Enforced: backend/calendar_sync/travel_rules.py::travel_rules_collection, backend/calendar_sync/travel_rules.py::travel_rule_detail

#### Scenario: Defaults and ordering
- **WHEN** a rule is created with only a keyword
- **THEN** it has zero minutes, empty category and an order one above the user's highest

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_create_defaults, backend/tests/test_from_event.py::TestTravelRuleCrud::test_omitted_order_assigned_max_plus_one, backend/tests/test_from_event.py::TestTravelRuleCrud::test_create_full_payload

#### Scenario: Per-user cap
- **WHEN** a user with 100 rules creates another
- **THEN** the response is 400 under `travel_rules`

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_per_user_cap

#### Scenario: Patch and delete
- **WHEN** a rule is patched with some fields, patched with an empty body, or deleted
- **THEN** only the sent fields change, the empty body gets 400, and delete returns `{"ok": true}`

Tests: backend/tests/test_from_event.py::TestTravelRuleCrud::test_patch_updates_fields, backend/tests/test_from_event.py::TestTravelRuleCrud::test_order_only_patch_preserves_calendar_name, backend/tests/test_from_event.py::TestTravelRuleCrud::test_patch_empty_body_rejected, backend/tests/test_from_event.py::TestTravelRuleCrud::test_delete

### Requirement: Atomic travel rule swap
The system SHALL swap the `order` values of two of the user's travel rules at `POST /api/calendar/travel-rules/swap/` in one transaction under the user lock and return the swapped rules. Equal, non-integer or boolean ids, invalid JSON or a non-object body SHALL give 400, an oversized body 413, and a missing or foreign id 404.
Enforced: backend/calendar_sync/travel_rules.py::travel_rules_swap, backend/schedules/http.py::parse_swap_body, backend/schedules/http.py::swap_ordering_field

#### Scenario: Swap two rules
- **WHEN** the user swaps two of their rules
- **THEN** their order values are exchanged under the user lock

Tests: backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_two_rules_swaps_order

#### Scenario: Rejected swaps
- **WHEN** an id is missing, belongs to another user, repeats, is not an integer, or the body is malformed or oversized
- **THEN** the response is 404, 400 or 413 and no order changes

Tests: backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_missing_id_returns_404, backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_cross_user_id_returns_404, backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_equal_ids_returns_400, backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_non_int_id_returns_400, backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_bool_id_returns_400, backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_invalid_json_returns_400, backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_non_dict_body_returns_400, backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_oversized_body_returns_413

#### Scenario: Failure rolls back
- **WHEN** the bulk update fails mid-swap
- **THEN** both rules keep their original order

Tests: backend/tests/test_travel_rules.py::TestTravelRuleSwap::test_swap_rolls_back_on_bulk_update_failure
