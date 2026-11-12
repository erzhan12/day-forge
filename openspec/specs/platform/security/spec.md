# platform/security Specification

## Purpose
Cross-cutting authentication, session, CSRF and transport rules for the Django backend. It covers the login gate on pages and APIs, the login and logout views, the session-identity header on API writes, Inertia history encryption, production-only settings, the shared JSON body parser and the SQLite production warning. Per-feature authorization (ownership, rate limits, integration checks) lives in the owning capability's spec.

## Requirements

### Requirement: Login gate on pages and APIs
The system SHALL require an authenticated session for every page and API view except the root redirect, the login view, `/privacy/`, `/terms/` and the two export routes, which authenticate themselves; a gated view reached anonymously SHALL redirect with 302 to `/accounts/login/`.
Enforced: backend/day_forge/settings.py::LOGIN_URL, backend/schedules/views.py::schedule_view, backend/schedules/api.py::create_block

#### Scenario: Anonymous page visit
- **WHEN** an anonymous client requests `/schedule/<date>/`
- **THEN** the response is 302 to `/accounts/login/`

Tests: backend/tests/test_views.py::TestScheduleView::test_unauthenticated_redirects

#### Scenario: Anonymous API write without identity header
- **WHEN** an anonymous client POSTs a block to `/api/schedules/<date>/blocks/` without an `X-Schedule-User` header
- **THEN** the response is 302 rather than a JSON body

Tests: backend/tests/test_views.py::TestCreateBlock::test_unauthenticated_returns_302

#### Scenario: Pages after logout
- **WHEN** a user logs out and then requests a schedule page
- **THEN** the response is 302 to `/accounts/login/`

Tests: backend/tests/test_inertia_identity.py::test_logout_login_response_invalidates_private_history

### Requirement: Login view
The system SHALL accept GET and POST on `/accounts/login/`, set the CSRF cookie, redirect an authenticated visitor to `/`, and on POST read `username` and `password` from a JSON object or form data, logging the user in and redirecting to a schedule page on valid credentials.
Enforced: backend/schedules/views.py::login_view

#### Scenario: Anonymous GET
- **WHEN** an anonymous client GETs `/accounts/login/`
- **THEN** the response is 200 and sets the `XSRF-TOKEN` cookie

Tests: backend/tests/test_views.py::TestLoginView::test_get_returns_200, backend/tests/test_views.py::TestLoginView::test_get_sets_csrf_cookie

#### Scenario: Valid form or JSON credentials
- **WHEN** valid credentials are POSTed as form data or as a JSON object
- **THEN** the response is 302 to a `/schedule/` URL and the session holds the user ID

Tests: backend/tests/test_views.py::TestLoginView::test_post_valid_credentials, backend/tests/test_views.py::TestLoginView::test_post_valid_json_credentials

#### Scenario: Already authenticated
- **WHEN** an authenticated user GETs `/accounts/login/`
- **THEN** the response is a 302 redirect

Tests: backend/tests/test_views.py::TestLoginView::test_authenticated_user_redirected

### Requirement: Login input rejection
The system MUST re-render the Login page with `non_field: "Invalid request body."` and without calling authentication when a JSON login body is malformed, not an object, or has a non-string `username` or `password`; failed authentication SHALL render `non_field: "Invalid credentials"`.
Enforced: backend/schedules/views.py::login_view, backend/common/http.py::parse_json_object

#### Scenario: Non-object or malformed JSON
- **WHEN** the JSON body is a list, number, string, boolean, null or undecodable bytes
- **THEN** the Login page renders with `Invalid request body.`, no session is created and authentication is not attempted

Tests: backend/tests/test_views.py::TestLoginInputValidation::test_non_object_json_rejected_before_authentication, backend/tests/test_views.py::TestLoginInputValidation::test_invalid_json_retains_login_error

#### Scenario: Non-string credential
- **WHEN** `username` or `password` is null, a list, an object, a number or a boolean
- **THEN** the Login page renders with `Invalid request body.` and authentication is not attempted

Tests: backend/tests/test_views.py::TestLoginInputValidation::test_non_string_credentials_rejected_before_authentication

#### Scenario: Missing, empty or wrong credentials
- **WHEN** credentials are missing, empty strings or wrong
- **THEN** authentication runs with empty-string defaults and the Login page renders with `Invalid credentials` and no session

Tests: backend/tests/test_views.py::TestLoginInputValidation::test_missing_or_empty_strings_retain_invalid_credentials, backend/tests/test_views.py::TestLoginView::test_post_invalid_credentials

### Requirement: Logout
The system SHALL accept only POST on `/accounts/logout/`, end the session and redirect to `/accounts/login/`; an anonymous POST SHALL also land on the login page.
Enforced: backend/schedules/views.py::logout_view

#### Scenario: Authenticated logout
- **WHEN** an authenticated user POSTs `/accounts/logout/`
- **THEN** the response is 302 to `/accounts/login/`

Tests: backend/tests/test_views.py::TestLogoutView::test_logout_redirects

#### Scenario: Anonymous logout
- **WHEN** an anonymous client POSTs `/accounts/logout/`
- **THEN** the response is 302 to `/accounts/login/`

Tests: backend/tests/test_views.py::TestLogoutView::test_unauthenticated_logout_redirects_to_login

### Requirement: CSRF via XSRF-TOKEN cookie and header
The system MUST enforce CSRF on unsafe requests using the `XSRF-TOKEN` cookie and the `X-XSRF-TOKEN` header; the cookie is readable by JavaScript and an unsafe request without a valid token SHALL be rejected with 403.
Enforced: backend/day_forge/settings.py::CSRF_COOKIE_NAME, backend/day_forge/settings.py::CSRF_HEADER_NAME, backend/day_forge/settings.py::CSRF_COOKIE_HTTPONLY

#### Scenario: Token sent in header
- **WHEN** a client obtains `XSRF-TOKEN` from the login GET and POSTs credentials with `X-XSRF-TOKEN`
- **THEN** the login succeeds with a 302 to a schedule page

Tests: backend/tests/test_views.py::TestLoginView::test_post_with_csrf_token

#### Scenario: Missing token on an API write
- **WHEN** an authenticated client sends PATCH or DELETE to `/api/blocks/<pk>/` without the CSRF header
- **THEN** the response is 403

Tests: backend/tests/test_views.py::TestBlockDetail::test_patch_without_csrf_token_rejected, backend/tests/test_views.py::TestBlockDetail::test_delete_without_csrf_token_rejected

### Requirement: Session owner check on unsafe API requests
The system MUST answer 401 `{"code": "session_invalid"}` before the view when a non-GET/HEAD/OPTIONS `/api/` request sends `X-Schedule-User` and the session is anonymous or belongs to a different user ID. Requests without the header and safe methods pass.
Enforced: backend/common/middleware.py::InertiaIdentityMiddleware.__call__

#### Scenario: Header names another account
- **WHEN** user B's session POSTs a restore with `X-Schedule-User` set to user A's ID
- **THEN** the response is 401 `session_invalid` and B's day is unchanged

Tests: backend/tests/test_inertia_identity.py::test_old_tab_cannot_restore_into_a_new_session_with_same_revision

#### Scenario: Header on an anonymous write
- **WHEN** an anonymous client POSTs a block with an `X-Schedule-User` header
- **THEN** the response is 401 `session_invalid` and no block is created

Tests: backend/tests/test_inertia_identity.py::test_identity_header_on_unauthenticated_write_returns_session_invalid

#### Scenario: Matching header or safe method
- **WHEN** the header matches the session user, or a GET carries a stale header
- **THEN** the request reaches the view

Tests: backend/tests/test_inertia_identity.py::test_current_session_identity_header_allows_normal_write, backend/tests/test_inertia_identity.py::test_old_session_identity_header_does_not_block_get

### Requirement: Page identity prop
The system SHALL share `auth_user_id` with every Inertia page: the session user's ID when authenticated, otherwise null, including on partial reloads.
Enforced: backend/common/middleware.py::InertiaIdentityMiddleware.__call__

#### Scenario: Identity follows the session
- **WHEN** the Login page is fetched anonymously, then a schedule page after login, then Login after logout
- **THEN** `auth_user_id` is null, then the user's ID (also in a partial reload), then null again

Tests: backend/tests/test_inertia_identity.py::test_page_identity_changes_with_session

### Requirement: Private browser history
The system SHALL mark Inertia pages with `encryptHistory: true` and every Login render with `clearHistory: true`, so Back cannot restore authenticated snapshots after logout or session expiry.
Enforced: backend/day_forge/settings.py::INERTIA_ENCRYPT_HISTORY, backend/schedules/views.py::_render_login

#### Scenario: Authenticated pages
- **WHEN** an authenticated user loads the schedule, settings or analytics page via Inertia
- **THEN** the page payload has `encryptHistory: true`

Tests: backend/tests/test_inertia_identity.py::test_authenticated_pages_encrypt_browser_history

#### Scenario: Login after logout or expiry
- **WHEN** logout redirects to Login, or Login is fetched without a session
- **THEN** the Login payload has `clearHistory: true`

Tests: backend/tests/test_inertia_identity.py::test_logout_login_response_invalidates_private_history, backend/tests/test_inertia_identity.py::test_login_after_session_expiry_also_clears_history

### Requirement: Client recognises an ended session
The frontend HTTP helper SHALL send `X-Schedule-User` when given an expected user, and MUST report `code: "session_invalid"` with status 401 for a redirect to `/accounts/login/` or a 401, except an explicit integration credential error; a 403 SHALL stay distinct.
Enforced: frontend/src/composables/useHttp.ts::requestJson

#### Scenario: Write bound to its account
- **WHEN** a write is sent with an expected user ID of 42
- **THEN** the request carries `X-Schedule-User: 42`

Tests: frontend/tests/useHttp.test.ts::mutation transport outcomes::binds a schedule write to the account that supplied its snapshot

#### Scenario: Login redirect or 401
- **WHEN** fetch follows a redirect to the login page, or the server answers 401
- **THEN** the result is `ok: false`, status 401, `code: "session_invalid"`

Tests: frontend/tests/useHttp.test.ts::mutation transport outcomes::recognizes a login redirect instead of treating its HTML 200 as a mutation, frontend/tests/useHttp.test.ts::mutation transport outcomes::recognizes an explicit unauthenticated response

#### Scenario: CSRF or integration failure
- **WHEN** the server answers 403, or 401 with `integration_credentials_error`
- **THEN** the result does not carry `session_invalid`

Tests: frontend/tests/useHttp.test.ts::mutation transport outcomes::keeps a CSRF rejection distinct from session invalidation, frontend/tests/useHttp.test.ts::mutation transport outcomes::preserves an explicit integration credential failure without invalidating the session

### Requirement: Debug mode and secret key
The system SHALL enable `DEBUG` only when the `DEBUG` variable is unset or exactly `"1"`, and MUST refuse to start with `DEBUG` off and no `DJANGO_SECRET_KEY`; in debug mode a fixed insecure development key is used.
Enforced: backend/day_forge/settings.py::DEBUG, backend/day_forge/settings.py::SECRET_KEY

#### Scenario: Production without a secret key
- **WHEN** settings load with `DEBUG=0` and `DJANGO_SECRET_KEY` unset or empty
- **THEN** settings import raises `RuntimeError`

### Requirement: Host and origin lists
The system SHALL use `localhost` and `127.0.0.1` as allowed hosts and the local Vite and Django origins as CSRF-trusted origins in debug mode; with `DEBUG` off it MUST read both from comma-separated `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, dropping empty entries.
Enforced: backend/day_forge/settings.py::ALLOWED_HOSTS, backend/day_forge/settings.py::CSRF_TRUSTED_ORIGINS

#### Scenario: Production lists from the environment
- **WHEN** settings load with `DEBUG=0` and `ALLOWED_HOSTS=app.example.com,`
- **THEN** `ALLOWED_HOSTS` is `["app.example.com"]`

### Requirement: Production transport hardening
With `DEBUG` off the system SHALL set secure session and CSRF cookies, redirect HTTP to HTTPS, send one-year HSTS including subdomains, and trust `X-Forwarded-Proto: https` and the forwarded host from the proxy. Sessions use `SameSite=Lax` and responses `nosniff` in all modes.
Enforced: backend/day_forge/settings.py::SECURE_SSL_REDIRECT, backend/day_forge/settings.py::SECURE_PROXY_SSL_HEADER, backend/day_forge/settings.py::SECURE_HSTS_SECONDS

#### Scenario: Behind the TLS proxy
- **WHEN** settings load with `DEBUG=0`
- **THEN** `SECURE_SSL_REDIRECT` is true and `SECURE_PROXY_SSL_HEADER` is `("HTTP_X_FORWARDED_PROTO", "https")`

Tests: backend/tests/test_settings_validation.py::test_secure_proxy_ssl_header_set_in_production

### Requirement: Shared JSON object parser
The shared parser SHALL return either an object or an error response: a body over 100,000 bytes gets 413 `errors.body` before decoding, an undecodable body gets 400 `Invalid JSON.`, and a non-object root gets 400 `Request body must be a JSON object.` under the caller's error field.
Enforced: backend/common/http.py::parse_json_object, backend/common/http.py::reject_oversized_body

#### Scenario: Malformed or non-object body
- **WHEN** the body is empty, whitespace, truncated, invalid UTF-8, or a JSON array, null, boolean, number or string
- **THEN** the result is a 400 with `{"errors": {"body": ...}}` naming invalid JSON or a non-object

Tests: backend/tests/test_http_json.py::test_parser_rejects_malformed_or_non_object_body

#### Scenario: Size limit
- **WHEN** a valid object is exactly 100,000 bytes, or invalid bytes exceed the limit with `error_field="detail"`
- **THEN** the first is accepted and the second gets 413 `{"errors": {"body": "Request body too large."}}`

Tests: backend/tests/test_http_json.py::test_body_limit_includes_boundary_and_precedes_decode

#### Scenario: Empty body allowed by the caller
- **WHEN** `allow_empty` is set and the body is exactly empty, or only whitespace
- **THEN** the first yields `{}` and the second still gets 400

Tests: backend/tests/test_http_json.py::test_parser_accepts_empty_body_only_when_enabled

#### Scenario: Caller response factory
- **WHEN** a caller passes a response factory that adds `Cache-Control: private, no-store`
- **THEN** the parser's error response carries that header

Tests: backend/tests/test_http_json.py::test_parser_uses_custom_response_factory_for_errors

### Requirement: SQLite production warning
The system SHALL emit system-check warning `schedules.W001` when `DEBUG` is off and the default database is SQLite, explaining the database-wide writer lock and bounded busy retries; it SHALL stay silent in debug mode or on another database vendor.
Enforced: backend/schedules/checks.py::warn_sqlite_in_production

#### Scenario: Production on SQLite
- **WHEN** checks run with `DEBUG=False` on SQLite
- **THEN** exactly one `schedules.W001` warning mentions the writer lock, revision and controlled conflict

Tests: backend/tests/test_checks.py::TestSqliteProductionWarning::test_warns_when_debug_false_on_sqlite

#### Scenario: Debug or PostgreSQL
- **WHEN** checks run with `DEBUG=True`, or with `DEBUG=False` on PostgreSQL
- **THEN** no warning is emitted

Tests: backend/tests/test_checks.py::TestSqliteProductionWarning::test_silent_when_debug_true, backend/tests/test_checks.py::TestSqliteProductionWarning::test_silent_when_debug_false_on_postgres
