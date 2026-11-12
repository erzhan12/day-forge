# platform/legal-pages Specification

## Purpose
`/privacy/` and `/terms/` are public legal pages linked from the Google OAuth consent screen. They are plain Django templates that render for anonymous visitors without the Vue bundle. Tests pin the disclosures the consent-screen review and the project's privacy notes depend on, so a copy edit cannot silently remove one.

## Requirements

### Requirement: Anonymous access
The system SHALL serve `/privacy/` (`privacy`) and `/terms/` (`terms`) with 200 to anonymous and authenticated visitors for GET and HEAD, without redirecting to login, and MUST reject other methods with 405.
Enforced: backend/schedules/legal_views.py::privacy_view, backend/schedules/legal_views.py::terms_view

#### Scenario: Anonymous GET
- **WHEN** an anonymous client GETs either page
- **THEN** the response is 200 with no `Location` header

Tests: backend/tests/test_legal_pages.py::TestPublicAccess::test_anonymous_get_returns_200, backend/tests/test_legal_pages.py::TestPublicAccess::test_anonymous_get_does_not_redirect_to_login, backend/tests/test_legal_pages.py::TestPublicAccess::test_reverse_names_resolve

#### Scenario: Signed-in GET and HEAD
- **WHEN** an authenticated client GETs either page, or any client sends HEAD
- **THEN** the response is 200

Tests: backend/tests/test_legal_pages.py::TestPublicAccess::test_authenticated_get_returns_200, backend/tests/test_legal_pages.py::TestPublicAccess::test_head_is_allowed

#### Scenario: POST
- **WHEN** a client POSTs either page
- **THEN** the response is 405

Tests: backend/tests/test_legal_pages.py::TestPublicAccess::test_post_is_rejected

### Requirement: Standalone HTML documents
The system SHALL render each page as a full HTML document from its own legal layout with inline CSS, without the Inertia layout, page payload or app bundle, with distinct titles and links to `/privacy/`, `/terms/` and `/`.
Enforced: backend/schedules/legal_views.py::_render_legal, backend/templates/legal/_layout.html::<style>

#### Scenario: No app bundle
- **WHEN** either page is fetched
- **THEN** the body starts with `<!DOCTYPE html>` and contains no `data-page` payload or app script

Tests: backend/tests/test_legal_pages.py::TestRendering::test_renders_a_standalone_html_document

#### Scenario: Navigation and titles
- **WHEN** either page is fetched
- **THEN** it links to both legal pages and home, and the titles are `Privacy Policy — Day Forge` and `Terms of Service — Day Forge`

Tests: backend/tests/test_legal_pages.py::TestRendering::test_pages_cross_link_and_link_home, backend/tests/test_legal_pages.py::TestRendering::test_titles_are_distinct

#### Scenario: Maintainer notes stay private
- **WHEN** either page is rendered
- **THEN** it contains no unrendered template tags and no internal setting or file names

Tests: backend/tests/test_legal_pages.py::TestRendering::test_maintainer_comments_never_reach_the_rendered_page

### Requirement: Revision date
The system SHALL show the revision date `LEGAL_LAST_UPDATED` on both pages, formatted as day, capitalised month name and four-digit year.
Enforced: backend/schedules/legal_views.py::LEGAL_LAST_UPDATED

#### Scenario: Date shown in the documented format
- **WHEN** either page is fetched
- **THEN** it contains the constant, which matches `D Month YYYY`

Tests: backend/tests/test_legal_pages.py::TestRendering::test_shows_the_revision_date, backend/tests/test_legal_pages.py::TestRendering::test_revision_date_keeps_the_documented_format

### Requirement: Contact address
The system SHALL show `LEGAL_CONTACT_EMAIL` (whitespace-trimmed) as a `mailto:` link on both pages, and when it is empty MUST render no `mailto:` and point readers to the support address on the Google OAuth consent screen.
Enforced: backend/day_forge/settings.py::LEGAL_CONTACT_EMAIL, backend/schedules/legal_views.py::_render_legal

#### Scenario: Address configured
- **WHEN** `LEGAL_CONTACT_EMAIL` is `ops@example.com`
- **THEN** both pages contain `href="mailto:ops@example.com"`

Tests: backend/tests/test_legal_pages.py::TestContactAddress::test_configured_address_renders_as_a_mailto

#### Scenario: Address unset
- **WHEN** `LEGAL_CONTACT_EMAIL` is empty
- **THEN** neither page contains `mailto:` and both mention the Google OAuth consent screen

Tests: backend/tests/test_legal_pages.py::TestContactAddress::test_unset_address_falls_back_without_a_blank_mailto

### Requirement: Privacy policy disclosures
The privacy page MUST name the CalDAV, Todoist, Habitica and Google Calendar integrations, state that credentials are encrypted at rest, disclose AI egress and verbatim logging, carry the Google Limited Use statement and scopes, and cover revocation and deletion.
Enforced: backend/templates/legal/privacy.html::Limited Use

#### Scenario: Integrations and credentials
- **WHEN** the privacy page is fetched
- **THEN** it names all four integrations and says `encrypted at rest`

Tests: backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_names_every_stored_credential_integration, backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_states_credentials_are_encrypted_at_rest

#### Scenario: AI egress and logging
- **WHEN** the privacy page is fetched
- **THEN** it discloses the prior conversation and server-built summary sent by chat, that clearing the thread keeps server records, draft generation, generic labels for imported event titles, and that AI messages are logged verbatim

Tests: backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_discloses_transcript_and_pending_summary_egress, backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_discloses_draft_history_egress, backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_discloses_imported_title_redaction_and_schedule_metadata, backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_states_ai_messages_are_logged_verbatim

#### Scenario: Google data use
- **WHEN** the privacy page is fetched
- **THEN** it cites the Google API Services User Data Policy and Limited Use, lists `calendar.readonly` and `userinfo.email`, and links Google account permissions for revocation

Tests: backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_carries_the_google_limited_use_disclosure, backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_declares_google_scopes_and_read_only_access, backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_explains_how_to_revoke_google_access

#### Scenario: Retention and cache window
- **WHEN** the privacy page is fetched
- **THEN** it has a `Retention and deletion` section and says events are cached `five minutes by default`, matching the 300-second CalDAV and Google cache defaults

Tests: backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_covers_deletion, backend/tests/test_legal_pages.py::TestPrivacyDisclosures::test_cache_window_prose_matches_the_settings_it_describes

### Requirement: Terms of service disclosures
The terms page MUST disclaim AI-generated content and warranties, state the service is provided as is with no uptime commitment or guaranteed backups, make the account holder responsible for their password, and link the privacy policy.
Enforced: backend/templates/legal/terms.html::Terms of Service

#### Scenario: Disclaimers present
- **WHEN** the terms page is fetched
- **THEN** it contains the AI-output, warranty, as-is, password-responsibility, uptime and backup statements and mentions the Privacy Policy

Tests: backend/tests/test_legal_pages.py::TestTermsDisclosures::test_disclaims_ai_output, backend/tests/test_legal_pages.py::TestTermsDisclosures::test_disclaims_warranties, backend/tests/test_legal_pages.py::TestTermsDisclosures::test_states_the_service_is_provided_as_is, backend/tests/test_legal_pages.py::TestTermsDisclosures::test_states_the_account_holder_owns_their_credentials, backend/tests/test_legal_pages.py::TestTermsDisclosures::test_makes_no_uptime_or_backup_promise, backend/tests/test_legal_pages.py::TestTermsDisclosures::test_links_to_the_privacy_policy
