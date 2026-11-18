## ADDED Requirements

### Requirement: Retained category catalogue refresh
While a snapshot is retained, the app root SHALL copy a valid category catalogue from the current authenticated, non-Login page without changing the retained date, blocks or time zone. The root's page-catalogue refresh MUST NOT change the retained catalogue for a missing or malformed catalogue, or while no snapshot is retained.
Enforced: frontend/src/composables/useFocusIndicatorController.ts::useFocusIndicatorController, frontend/src/composables/useCategories.ts::useCategories

#### Scenario: Category colour changed in Settings
- **WHEN** the user changes the active block's category colour in Settings while a snapshot is retained and Schedule is unmounted
- **THEN** the open PiP uses the new colours and keeps the previously published date and blocks

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::updates the open PiP rail when the active category colour changes on Settings page props after the publisher unmounts

#### Scenario: Invalid or absent catalogue
- **WHEN** Schedule is unmounted, a snapshot remains retained, no session boundary has occurred, and the current page omits `categories` or provides a malformed catalogue
- **THEN** the retained catalogue is left unchanged

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::keeps the retained catalogue when Settings omits or provides a malformed catalogue

#### Scenario: Leftover catalogue after session clear
- **WHEN** Login or a user change has cleared the snapshot
- **THEN** a leftover or newly assigned catalogue on page props does not restore retained schedule data or retained colours

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::does not restore retained colours after Login when a new catalogue arrives, frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::does not restore the previous user's colours after an account switch, frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::does not apply a leftover catalogue after Login once the page is authenticated again

#### Scenario: Uninitialized page component
- **WHEN** `page.component` is unset
- **THEN** a valid catalogue on page props does not refresh retained colours, and the session is not treated as logout

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::does not refresh the catalogue while the page component is uninitialized

#### Scenario: Missing identity
- **WHEN** `auth_user_id` is omitted
- **THEN** a valid catalogue on page props does not refresh retained colours

Tests: frontend/tests/FocusIndicatorHost.test.ts::FocusIndicatorHost::does not refresh the catalogue when auth_user_id is missing

#### Scenario: Category reload carries identity
- **WHEN** Settings reloads the category catalogue after a create, update or delete
- **THEN** the partial reload also requests `auth_user_id`, so the root sees the current identity together with the new catalogue

Tests: frontend/tests/useCategories.test.ts::useCategories::requests auth_user_id with the categories refresh, frontend/tests/useCategories.test.ts::useCategories::requests auth_user_id with the post-delete refresh, backend/tests/test_inertia_identity.py::test_settings_category_reload_needs_explicit_identity
