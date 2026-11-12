# export/daily-export Specification

## Purpose
Personal, read-only Markdown/JSON export of one day's schedule at `GET /api/export/daily/{date}/`, plus
session-only management of the personal export token that can authenticate it. Covers the shared
Markdown formatter contract, Bearer-vs-session authentication, owner scoping, date/format parsing,
token lifecycle (create, status, revoke) and the rule that the token authenticates nothing else.

## Requirements

### Requirement: Daily export Markdown rendering
The system SHALL render a header `## day-forge · <date>`, a `blocks: <done>/<planned> done` line and, when blocks exist, one `- [x|  ] HH:MM <title>[ (<category>)] <duration>` line per block, joined by blank lines with no trailing newline.
Enforced: backend/schedules/daily_export.py::format_daily_export, backend/schedules/daily_export.py::_render_block_line

#### Scenario: Day with one completed block
- **WHEN** a day has one completed `health` block from 09:00 to 10:00 titled "Gym"
- **THEN** the Markdown is `## day-forge · 2026-08-29\n\nblocks: 1/1 done\n\n- [x] 09:00 Gym (health) 1h`

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_default_response_is_markdown_with_charset, backend/tests/test_daily_export.py::test_markdown_fixture_matches_exactly

#### Scenario: Empty day
- **WHEN** a day has no blocks
- **THEN** the Markdown is only the header and `blocks: 0/0 done`, with no block list and no trailing newline

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_absent_day_returns_empty_report_without_creating_schedule, frontend/tests/dailyExport.test.ts::formatDailyExport::keeps an empty export to its header and summary without a trailing newline

#### Scenario: Category other omits the parenthesised category
- **WHEN** a block's category is `other`
- **THEN** its line has no ` (<category>)` suffix; any other category is shown in parentheses

Tests: backend/tests/test_daily_export.py::test_markdown_fixture_matches_exactly

#### Scenario: Titles are emitted verbatim
- **WHEN** a block title contains non-ASCII characters or a newline
- **THEN** the title is written unchanged into the block line, newline included

Tests: backend/tests/test_daily_export.py::test_markdown_fixture_matches_exactly

### Requirement: Daily export block ordering and durations
The formatter SHALL list blocks by start time then `sort_order` (missing treated as 0, ties stable), show duration as `Nm`, `Nh` or `Nh Mm`, and render a zero or negative span as `0m`, without mutating its input.
Enforced: backend/schedules/daily_export.py::_sorted_blocks, backend/schedules/daily_export.py::_format_duration_minutes

#### Scenario: Unsorted input with tied start times
- **WHEN** blocks arrive out of order and two share a start time
- **THEN** they are rendered by start time, then by `sort_order`, keeping input order on full ties

Tests: backend/tests/test_daily_export.py::test_markdown_fixture_matches_exactly

#### Scenario: Nonpositive duration
- **WHEN** a block's end time equals or precedes its start time
- **THEN** its duration renders as `0m`

Tests: backend/tests/test_daily_export.py::test_markdown_fixture_matches_exactly

#### Scenario: Input is not mutated
- **WHEN** the formatter is called with a list of block dicts
- **THEN** the list order and each block's values are unchanged afterwards

Tests: backend/tests/test_daily_export.py::test_formatter_does_not_mutate_input_blocks, frontend/tests/dailyExport.test.ts::formatDailyExport::does not mutate the input blocks array

### Requirement: Daily export note normalization
The formatter SHALL trim and collapse a supplied note using ECMAScript whitespace semantics (U+FEFF is whitespace; U+0085 and U+001C-U+001F are not) and append `note: <text>` only when the result is non-empty.
Enforced: backend/schedules/daily_export.py::_normalize_note, backend/schedules/daily_export.py::_JS_WHITESPACE_CODEPOINTS

#### Scenario: Blank or absent note
- **WHEN** the note is absent, empty or whitespace only
- **THEN** no `note:` line is emitted

Tests: backend/tests/test_daily_export.py::test_notes_fixture_matches_exactly

#### Scenario: Characters JavaScript does not treat as whitespace
- **WHEN** the note contains U+0085 or U+001C-U+001F
- **THEN** those characters are preserved, while a leading or embedded U+FEFF is trimmed or collapsed

Tests: backend/tests/test_daily_export.py::test_notes_fixture_matches_exactly

### Requirement: Backend and frontend formatter parity
The Python formatter and `frontend/src/utils/dailyExport.ts::formatDailyExport` MUST produce byte-identical Markdown for the shared fixtures in `backend/tests/fixtures/daily_export/`.
Enforced: backend/schedules/daily_export.py::format_daily_export, frontend/src/utils/dailyExport.ts::formatDailyExport

#### Scenario: Shared fixture case
- **WHEN** a fixture case from `markdown.json` or `notes.json` is formatted by either implementation
- **THEN** the output equals the fixture's `expected` string byte for byte

Tests: backend/tests/test_daily_export.py::test_markdown_fixture_matches_exactly, backend/tests/test_daily_export.py::test_notes_fixture_matches_exactly, frontend/tests/dailyExport.test.ts::formatDailyExport (shared backend/frontend fixtures)

### Requirement: Daily export response formats
The export endpoint SHALL return `text/markdown; charset=utf-8` by default or for `?format=markdown`, a JSON report for `?format=json`, and 400 for any other `format` value.
Enforced: backend/schedules/export_api.py::daily_export, backend/schedules/export_api.py::_resolve_format

#### Scenario: Default and explicit Markdown are identical
- **WHEN** the export is requested without `format` and with `format=markdown`
- **THEN** both responses have the same body and `Content-Type`

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_explicit_markdown_format_matches_default

#### Scenario: JSON report shape
- **WHEN** the export is requested with `format=json`
- **THEN** the body has `date`, `blocks`, `completed_count`, `planned_count`, `note` and a `markdown` field equal to the Markdown export

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_json_format_contains_expected_fields_and_matches_markdown

#### Scenario: Unknown format
- **WHEN** the export is requested with `format=yaml`
- **THEN** the response is 400 with `errors.detail`

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_invalid_format_rejected

### Requirement: Export blocks expose only formatter fields
Each exported block SHALL contain only `title`, `start_time`, `end_time` (canonical `HH:MM`), `category`, `is_completed` and `sort_order`, never a block `id` or `restore_proof`.
Enforced: backend/schedules/export_api.py::_export_block

#### Scenario: JSON block fields
- **WHEN** a JSON export includes a block
- **THEN** the block object has exactly the formatter fields and no `id` or `restore_proof`

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_json_format_contains_expected_fields_and_matches_markdown

### Requirement: Export reads current owner-scoped day without creating rows
The export SHALL read the authenticated owner's day through a read-only snapshot, report counts of current blocks regardless of schedule status, and return a 200 empty `0/0` report for an absent day without creating any row.
Enforced: backend/schedules/export_api.py::daily_export, backend/schedules/reads.py::read_schedule_day

#### Scenario: Absent day
- **WHEN** the owner has no schedule for the requested date
- **THEN** the response is 200 with no blocks and `0/0` counts, and no `Schedule` is created

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_absent_day_returns_empty_report_without_creating_schedule

#### Scenario: Draft day counts current blocks
- **WHEN** the requested day is a draft with one incomplete block
- **THEN** `planned_count` is 1 and `completed_count` is 0

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_counts_reflect_current_blocks_on_a_draft_day

#### Scenario: Another user's blocks are never exported
- **WHEN** two users have schedules on the same date, or only another user has one
- **THEN** each export contains only the requesting owner's blocks

Tests: backend/tests/test_daily_export_api.py::TestOwnership::test_two_owners_same_date_see_only_their_own_blocks, backend/tests/test_daily_export_api.py::TestOwnership::test_foreign_only_day_is_invisible_to_the_requesting_owner

### Requirement: HTTP export note is always empty
The export endpoint SHALL always send an empty note: it never substitutes `DailyReview` notes and never persists a note.
Enforced: backend/schedules/export_api.py::daily_export

#### Scenario: JSON note field
- **WHEN** a JSON export is returned
- **THEN** `note` is `""` and the Markdown has no `note:` line

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_json_format_contains_expected_fields_and_matches_markdown

### Requirement: Export date parsing
The export SHALL accept `today` or a strict zero-padded `YYYY-MM-DD` calendar date, return 400 for anything else, and resolve `today` in the owner's saved time zone (UTC fallback) without creating settings or schedule rows.
Enforced: backend/schedules/export_api.py::_parse_date, backend/schedules/window.py::user_local_date_readonly

#### Scenario: Malformed or impossible date
- **WHEN** the date is `2026-13-01`, `2026-02-30`, `20260829`, `2026-W35-6`, `2026-8-29` or `not-a-date`
- **THEN** the response is 400 with `errors.detail`

Tests: backend/tests/test_daily_export_api.py::TestDateParsing::test_invalid_dates_rejected_with_400

#### Scenario: Today in the saved time zone
- **WHEN** the owner's saved zone is on a different calendar date than UTC
- **THEN** `today` resolves to the date in the saved zone

Tests: backend/tests/test_daily_export_api.py::TestDateParsing::test_today_resolves_using_saved_time_zone

#### Scenario: Today falls back to UTC
- **WHEN** the owner has no settings row or a stored zone that is invalid
- **THEN** `today` resolves to the UTC date and no settings row is created

Tests: backend/tests/test_daily_export_api.py::TestDateParsing::test_today_falls_back_to_utc_without_a_settings_row, backend/tests/test_daily_export_api.py::TestDateParsing::test_today_falls_back_to_utc_for_an_invalid_stored_zone, backend/tests/test_daily_export_api.py::TestDateParsing::test_today_creates_no_schedule_or_settings_rows

#### Scenario: Today does not need the SQLite writer
- **WHEN** another connection holds the SQLite write reservation
- **THEN** a `today` export still returns 200

Tests: backend/tests/test_daily_export_api.py::TestDateParsing::test_today_succeeds_while_an_independent_writer_holds_the_sqlite_reservation

### Requirement: Export authentication precedence
The export SHALL authenticate a present `Authorization` header only as a valid `Bearer` export token of an active owner, ignoring any session; otherwise accept an active session; otherwise return 401 JSON, never a login redirect.
Enforced: backend/schedules/export_auth.py::resolve_export_owner, backend/schedules/export_tokens.py::authenticate

#### Scenario: Bearer token or session alone
- **WHEN** a request carries only a valid Bearer export token, or only an active session
- **THEN** the export returns 200

Tests: backend/tests/test_daily_export_api.py::TestAuthentication::test_bearer_without_session_authenticates, backend/tests/test_daily_export_api.py::TestAuthentication::test_session_without_bearer_authenticates

#### Scenario: Bad Authorization header with a valid session
- **WHEN** the header is not `Bearer ` prefixed or carries an unknown token, and a valid session is present
- **THEN** the response is 401

Tests: backend/tests/test_daily_export_api.py::TestAuthentication::test_malformed_authorization_header_returns_401_even_with_session, backend/tests/test_daily_export_api.py::TestAuthentication::test_invalid_bearer_token_returns_401_even_with_session

#### Scenario: Bearer wins over another user's session
- **WHEN** a valid Bearer token for one user is sent alongside another user's session
- **THEN** the export is for the token owner only

Tests: backend/tests/test_daily_export_api.py::TestAuthentication::test_valid_bearer_takes_precedence_over_a_different_users_session

#### Scenario: Revoked token or inactive owner
- **WHEN** the token was revoked, or its owner or the session user is inactive
- **THEN** the response is 401

Tests: backend/tests/test_daily_export_api.py::TestAuthentication::test_revoked_bearer_token_returns_401, backend/tests/test_daily_export_api.py::TestAuthentication::test_inactive_bearer_owner_rejected, backend/tests/test_daily_export_api.py::TestAuthentication::test_inactive_session_owner_rejected

#### Scenario: Anonymous or query-string credential
- **WHEN** there is no header and no session, even if the token is passed as a query parameter
- **THEN** the response is 401 JSON with `errors.detail` and no `Location` header

Tests: backend/tests/test_daily_export_api.py::TestAuthentication::test_no_authorization_header_and_no_session_returns_401_json, backend/tests/test_daily_export_api.py::TestAuthentication::test_query_string_cannot_authenticate

### Requirement: Export token authenticates no other API route
A Bearer export token MUST NOT authenticate any `/api/` route other than the daily export: such a request SHALL get the same status as the anonymous request.
Enforced: backend/schedules/export_auth.py::resolve_export_owner, backend/schedules/export_token_api.py::export_token

#### Scenario: Bearer-only request to another route
- **WHEN** any other `/api/` route in the live urlconf is called with any method and only a Bearer export token
- **THEN** the status equals the anonymous status and never turns a rejection into a success

Tests: backend/tests/test_daily_export_api.py::test_bearer_only_request_behaves_like_an_unauthenticated_request, backend/tests/test_daily_export_api.py::test_matrix_covers_every_other_api_route_in_the_urlconf

### Requirement: Export endpoints send private no-store responses
Every response from the export and token-management endpoints, including errors, SHALL carry `Cache-Control: private, no-store`.
Enforced: backend/schedules/export_api.py::_error, backend/schedules/export_auth.py::_unauthorized, backend/schedules/export_token_api.py::_response

#### Scenario: Export response
- **WHEN** an export request succeeds or is rejected with 401
- **THEN** the response has `Cache-Control: private, no-store`

Tests: backend/tests/test_daily_export_api.py::TestMarkdownAndJsonParity::test_response_is_private_no_store, backend/tests/test_daily_export_api.py::TestAuthentication::test_no_authorization_header_and_no_session_returns_401_json

#### Scenario: Token-management response
- **WHEN** a GET, POST or DELETE on the token endpoint succeeds or is denied
- **THEN** the response has `Cache-Control: private, no-store`

Tests: backend/tests/test_export_token_api.py::TestCacheHeaders::test_every_response_is_private_no_store, backend/tests/test_export_token_api.py::TestCacheHeaders::test_denial_response_is_also_private_no_store

### Requirement: Export allowed methods
The export endpoint SHALL accept only GET and the token endpoint only GET, POST and DELETE; other methods return 405.
Enforced: backend/schedules/export_api.py::daily_export, backend/schedules/export_token_api.py::export_token

#### Scenario: Write method on the export
- **WHEN** POST, PATCH, PUT or DELETE is sent to the export endpoint
- **THEN** the response is 405

Tests: backend/tests/test_daily_export_api.py::TestUnsupportedMethods::test_non_get_methods_rejected

#### Scenario: PATCH or PUT on the token endpoint
- **WHEN** PATCH or PUT is sent to `/api/user/export-token/`
- **THEN** the response is 405

Tests: backend/tests/test_export_token_api.py::TestUnsupportedMethods::test_rejected_with_405

### Requirement: Export token credential format and storage
The system SHALL generate tokens as `dfx_` plus 32 random URL-safe bytes, persist only the 64-char SHA-256 hex digest of the full token (unique), and delete the token with its user.
Enforced: backend/schedules/export_tokens.py::generate_raw_token, backend/schedules/export_tokens.py::hash_token, backend/schedules/models.py::PersonalExportToken

#### Scenario: Created token
- **WHEN** a token is created
- **THEN** it starts with `dfx_`, is longer than 36 characters, and the stored row holds only its SHA-256 digest

Tests: backend/tests/test_export_tokens.py::test_create_token_returns_prefixed_credential_with_enough_entropy, backend/tests/test_export_tokens.py::test_created_row_persists_only_the_digest_never_the_raw_value, backend/tests/test_export_token_api.py::TestCreation::test_create_persists_only_the_digest

#### Scenario: Uniqueness
- **WHEN** many tokens are generated
- **THEN** every raw token and every digest is distinct

Tests: backend/tests/test_export_tokens.py::test_generated_tokens_are_unique_across_many_calls

#### Scenario: User deletion
- **WHEN** the token owner is deleted
- **THEN** the token row is deleted and the raw token no longer authenticates

Tests: backend/tests/test_export_tokens.py::test_user_deletion_cascades_to_token

### Requirement: Export token authentication lookup
Token authentication SHALL reject values without the `dfx_` prefix, resolve a digest only to an active owner, and read the database on every call so revocation applies to the next request.
Enforced: backend/schedules/export_tokens.py::authenticate

#### Scenario: Valid token
- **WHEN** a live token of an active user is presented
- **THEN** that user is returned

Tests: backend/tests/test_export_tokens.py::test_authenticate_resolves_the_owning_user, backend/tests/test_export_tokens.py::test_owner_isolation_between_two_users_tokens

#### Scenario: Unknown, malformed or inactive
- **WHEN** the token is unknown, lacks the prefix, or belongs to an inactive user
- **THEN** no user is returned

Tests: backend/tests/test_export_tokens.py::test_authenticate_rejects_unknown_or_malformed_tokens, backend/tests/test_export_tokens.py::test_authenticate_rejects_inactive_user

### Requirement: One export token per user
The system SHALL allow at most one token per user: creation fails with `token_exists` while one exists, revocation deletes it idempotently, and both run under the per-user maintenance lock.
Enforced: backend/schedules/export_tokens.py::create_token, backend/schedules/export_tokens.py::revoke_token, backend/schedules/models.py::PersonalExportToken

#### Scenario: Duplicate creation
- **WHEN** a user with a token creates another
- **THEN** creation fails, the existing token still authenticates, and `POST` returns 409 with `code: token_exists`

Tests: backend/tests/test_export_tokens.py::test_create_twice_without_revoking_raises_and_does_not_replace, backend/tests/test_export_token_api.py::TestCreation::test_duplicate_create_without_revoking_returns_409_token_exists

#### Scenario: Revoke and recreate
- **WHEN** a user revokes their token and creates a new one
- **THEN** the old token stops authenticating and the new token is unrelated to it

Tests: backend/tests/test_export_tokens.py::test_revoke_deletes_the_row_and_disables_authentication, backend/tests/test_export_tokens.py::test_recreation_after_revoke_produces_an_unrelated_credential, backend/tests/test_export_token_api.py::TestRevocationAndRecreation::test_recreate_after_revoke_succeeds_with_an_unrelated_credential

#### Scenario: Revoke with no token
- **WHEN** a user without a token revokes
- **THEN** the call succeeds and `DELETE` returns 204

Tests: backend/tests/test_export_tokens.py::test_revoke_is_idempotent_when_no_token_exists, backend/tests/test_export_token_api.py::TestRevocationAndRecreation::test_revoke_is_idempotent_when_absent, backend/tests/test_export_token_api.py::TestRevocationAndRecreation::test_revoke_returns_204

### Requirement: Export token management API responses
`/api/user/export-token/` SHALL return `{has_token, created_at}` on GET without the token or digest, `201 {token, has_token: true, created_at}` on POST with the raw token shown only then, and 204 on DELETE, for the session user only.
Enforced: backend/schedules/export_token_api.py::export_token, backend/schedules/export_token_api.py::_status_payload

#### Scenario: Status
- **WHEN** a session user calls GET with and without a token
- **THEN** the body is `{"has_token": false, "created_at": null}` or `has_token: true` with an ISO `created_at` and no secret

Tests: backend/tests/test_export_token_api.py::TestStatus::test_no_token_reports_has_token_false, backend/tests/test_export_token_api.py::TestStatus::test_existing_token_reports_has_token_true_with_created_at_but_no_secret

#### Scenario: Create
- **WHEN** a session user without a token calls POST
- **THEN** the response is 201 with the raw `token`, `has_token: true` and `created_at`

Tests: backend/tests/test_export_token_api.py::TestCreation::test_create_returns_201_with_raw_token_once

#### Scenario: Owner isolation
- **WHEN** one user creates, inspects or revokes a token
- **THEN** another user's token is unaffected

Tests: backend/tests/test_export_token_api.py::TestOwnerIsolation::test_each_user_manages_only_their_own_token

### Requirement: Export token management is session-only
The token endpoint SHALL return 401 JSON (no redirect) for anonymous or inactive sessions and for any request with an `Authorization` header, even alongside a valid session.
Enforced: backend/schedules/export_token_api.py::export_token

#### Scenario: Anonymous request
- **WHEN** GET, POST or DELETE is sent without a session
- **THEN** the response is 401 JSON, not a login redirect

Tests: backend/tests/test_export_token_api.py::TestDenial::test_anonymous_get_returns_401_json_not_a_login_redirect, backend/tests/test_export_token_api.py::TestDenial::test_anonymous_post_returns_401, backend/tests/test_export_token_api.py::TestDenial::test_anonymous_delete_returns_401

#### Scenario: Bearer header present
- **WHEN** a valid export token is sent as Bearer, with or without a valid session
- **THEN** the response is 401

Tests: backend/tests/test_export_token_api.py::TestDenial::test_bearer_credential_alone_is_rejected, backend/tests/test_export_token_api.py::TestDenial::test_bearer_credential_with_a_different_valid_session_is_still_rejected

#### Scenario: Inactive session user
- **WHEN** the session user is inactive
- **THEN** the response is 401

Tests: backend/tests/test_export_token_api.py::TestDenial::test_inactive_session_owner_rejected

### Requirement: Export token writes follow the shared write guards
Token POST and DELETE SHALL be subject to CSRF, the frontend-release handshake and the `X-Schedule-User` identity check, each rejecting before any token change.
Enforced: backend/common/middleware.py::FrontendVersionMiddleware, backend/common/middleware.py::InertiaIdentityMiddleware

#### Scenario: Missing CSRF token
- **WHEN** POST or DELETE is sent without a CSRF token
- **THEN** the response is 403 and the token state is unchanged

Tests: backend/tests/test_export_token_api.py::TestCsrfEnforcement::test_post_without_csrf_token_rejected, backend/tests/test_export_token_api.py::TestCsrfEnforcement::test_delete_without_csrf_token_rejected

#### Scenario: Stale frontend release
- **WHEN** POST sends an `X-Frontend-Version` that differs from the current release
- **THEN** the response is 409 `frontend_outdated` and no token is created

Tests: backend/tests/test_export_token_api.py::TestStaleReleaseAndAccountHeaders::test_stale_frontend_version_rejects_create_before_the_view_executes

#### Scenario: Identity header
- **WHEN** POST sends an `X-Schedule-User` that does not match the session user
- **THEN** the response is 401 `session_invalid` and no token is created; a matching header allows the write

Tests: backend/tests/test_export_token_api.py::TestStaleReleaseAndAccountHeaders::test_session_mismatched_identity_header_rejects_the_write, backend/tests/test_export_token_api.py::TestStaleReleaseAndAccountHeaders::test_current_session_identity_header_allows_the_write
