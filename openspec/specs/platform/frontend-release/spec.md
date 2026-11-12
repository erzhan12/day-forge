# platform/frontend-release Specification

## Purpose
Binds the running frontend bundle to the backend release so an old tab cannot write into a newer or older API. The backend loads the packaged release identity at production startup, exposes it to HTML and Inertia, refreshes stale Inertia navigations and rejects stale JSON API requests before any view runs. The frontend sends its bundle identity on every request and offers a manual reload without replaying the rejected write.

## Requirements

### Requirement: Packaged release identity
In production the system MUST load `.vite/release.json` from the frontend build directory and fail startup with `ImproperlyConfigured` unless it names a valid version, a script and a styles list whose paths are `assets/<name>` files that exist. Debug mode uses version `development`.
Enforced: backend/day_forge/frontend_release.py::load_frontend_release, backend/day_forge/settings.py::FRONTEND_RELEASE, backend/day_forge/settings.py::INERTIA_VERSION

#### Scenario: Valid build
- **WHEN** the release file names `release-a` with existing hashed script and stylesheet under `assets/`
- **THEN** the loaded release has version `release-a` and those asset paths

Tests: backend/tests/test_frontend_release.py::test_release_reads_only_packaged_assets

#### Scenario: Asset path outside the build
- **WHEN** the script path is `../outside.js`
- **THEN** loading raises `ImproperlyConfigured`

Tests: backend/tests/test_frontend_release.py::test_release_reads_only_packaged_assets

#### Scenario: Missing or invalid build
- **WHEN** the release file is absent, not JSON, an empty object, a list, null, or names a missing asset
- **THEN** loading raises `ImproperlyConfigured` with a message about the frontend build

Tests: backend/tests/test_frontend_release.py::test_missing_or_invalid_build_fails_closed

### Requirement: HTML and page share the release
The system SHALL render the release version in the `frontend-version` meta tag, load the packaged script and stylesheets from static files, and report the same version in Inertia page payloads.
Enforced: backend/day_forge/context_processors.py::vite_dev_mode, backend/templates/base.html::frontend-version

#### Scenario: Production login page
- **WHEN** the login page is rendered under release `release-a`
- **THEN** the HTML carries `content="release-a"` and the release's static asset URLs, and an Inertia request gets `version: "release-a"`

Tests: backend/tests/test_frontend_release.py::test_html_assets_and_inertia_page_share_the_packaged_identity

### Requirement: Stale Inertia navigation refreshes
Outside development, the system MUST answer an Inertia GET or HEAD whose `X-Inertia-Version` differs from the release with 409 and `X-Inertia-Location` set to the requested URL, without running the view.
Enforced: backend/common/middleware.py::FrontendVersionMiddleware.__call__

#### Scenario: Old tab navigates
- **WHEN** an Inertia GET for a schedule page carries a different version, including after rollback
- **THEN** the response is 409 with `X-Inertia-Location` of that page and the view is not called

Tests: backend/tests/test_frontend_release.py::test_stale_inertia_visit_does_not_execute_page_bootstrap, backend/tests/test_frontend_release.py::test_stale_inertia_visit_with_full_middleware_stack

### Requirement: Auth POST keeps its redirect on version mismatch
The system SHALL apply the Inertia stale-version refresh only to GET and HEAD, so an Inertia POST with an old version runs normally and keeps its redirect.
Enforced: backend/common/middleware.py::ReleaseInertiaMiddleware.is_stale

#### Scenario: Logout from an old tab
- **WHEN** an Inertia logout POST carries an old version
- **THEN** the session ends and the response is 302 to `/accounts/login/`

Tests: backend/tests/test_frontend_release.py::test_stale_inertia_logout_redirects_to_login_not_post_only_logout

### Requirement: Stale API requests are refused before the view
Outside development, the system MUST answer an `/api/` request with 409 `code: "frontend_outdated"` and `Cache-Control: no-store` when `X-Frontend-Version` differs from the release, or is missing on a non-GET/HEAD/OPTIONS method. Headerless reads and non-API paths pass.
Enforced: backend/common/middleware.py::FrontendVersionMiddleware.__call__

#### Scenario: Write from another release
- **WHEN** a POST, PATCH, PUT or DELETE to `/api/` names an older or newer release
- **THEN** the response is 409 `frontend_outdated` with `no-store` and the view is not called

Tests: backend/tests/test_frontend_release.py::test_upgrade_and_rollback_refuse_stale_writes_before_view, backend/tests/test_frontend_release.py::test_stale_real_api_write_leaves_database_unchanged

#### Scenario: Legacy client without the header
- **WHEN** a headerless client POSTs to `/api/`, GETs `/api/`, or POSTs to `/accounts/logout/`
- **THEN** the API POST is 409 while the GET and the logout POST reach their views

Tests: backend/tests/test_frontend_release.py::test_legacy_missing_identity_refuses_writes_but_allows_reads

#### Scenario: Read with an explicit stale header
- **WHEN** an export GET carries an old `X-Frontend-Version`, or no header
- **THEN** the first is 409 `frontend_outdated` and the second succeeds

Tests: backend/tests/test_frontend_release.py::test_explicitly_stale_version_header_rejects_export_get, backend/tests/test_frontend_release.py::test_headerless_export_get_succeeds_under_a_production_shaped_release

### Requirement: No API handshake in development
The system SHALL skip the API release check when the release version is `development`, whatever `X-Frontend-Version` is sent.
Enforced: backend/common/middleware.py::FrontendVersionMiddleware.__call__

#### Scenario: Dev write
- **WHEN** the server version is `development` and a POST to `/api/` sends no header, an old version or `development`
- **THEN** the request reaches the view

Tests: backend/tests/test_frontend_release.py::test_development_allows_api_writes_without_a_release_handshake

### Requirement: Client release identity and reload notice
The frontend SHALL send `X-Frontend-Version` with the identity of the bundle that was loaded, and on a 409 `frontend_outdated` MUST show a Reload notice without repeating the request; other 409 codes SHALL not show it.
Enforced: frontend/src/composables/useFrontendRelease.ts::frontendVersionHeader, frontend/src/composables/useFrontendRelease.ts::markFrontendOutdated, frontend/src/composables/useHttp.ts::requestJson

#### Scenario: Identity fixed at load
- **WHEN** the `frontend-version` meta tag changes after the bundle loaded
- **THEN** later requests still send the original version

Tests: frontend/tests/frontendRelease.test.ts::keeps the running bundle identity after history/page state changes

#### Scenario: Release rejection
- **WHEN** a PATCH returns 409 `frontend_outdated`
- **THEN** fetch was called once and an alert warning about unsent text offers a Reload button

Tests: frontend/tests/frontendRelease.test.ts::shows an explicit reload notice for a release rejection without replaying the write

#### Scenario: Ordinary revision conflict
- **WHEN** a PATCH returns 409 `schedule_changed`
- **THEN** the outdated flag stays false

Tests: frontend/tests/frontendRelease.test.ts::does not mistake an ordinary revision conflict for a new release
