# templates/preferences Specification

## Purpose
Each user has one preferences row holding UI settings: theme, AI chat suggestions and the default gap between blocks. This spec covers reading and patching preferences, normalization of corrupt stored values, response caching headers and per-user isolation. It also covers the props the `/settings/` Inertia page receives, including the theme used on a hard load.

## Requirements

### Requirement: Read user preferences
The system SHALL return `GET /api/user/preferences/` as `{theme, default_block_gap_minutes, chat_suggestions}` for the authenticated user, creating a default row (theme `classic`, gap `10`, unset suggestions) on first access. Anonymous requests SHALL be redirected to login.
Enforced: backend/templates_mgr/api.py::user_preferences, backend/templates_mgr/preferences.py::get_user_preferences

#### Scenario: First visit
- **WHEN** a user with no preferences row requests `GET /api/user/preferences/`
- **THEN** a row is created and the response is theme `classic`, gap `10`, and the three default suggestions

Tests: backend/tests/test_user_preferences_api.py::test_get_first_call_returns_default_classic, backend/tests/test_user_preferences_api.py::test_helper_creates_default_row_on_first_access

#### Scenario: Saved values
- **WHEN** a user with a saved theme and ordered suggestions requests their preferences
- **THEN** the response returns the saved theme and the suggestions in saved order

Tests: backend/tests/test_user_preferences_api.py::test_get_returns_saved_theme, backend/tests/test_user_preferences_api.py::test_get_returns_saved_ordered_suggestions

#### Scenario: Anonymous request
- **WHEN** an unauthenticated client requests or patches preferences
- **THEN** no preference data is returned

Tests: backend/tests/test_user_preferences_api.py::test_get_requires_auth, backend/tests/test_user_preferences_api.py::test_patch_requires_auth

### Requirement: Exactly one preferences row per user
The system MUST keep at most one `UserPreferences` row per user (one-to-one), and concurrent first-visit requests SHALL end with exactly one row.
Enforced: backend/templates_mgr/models.py::UserPreferences.user, backend/templates_mgr/preferences.py::get_user_preferences

#### Scenario: Concurrent first visits
- **WHEN** two requests for the same new user call `get_user_preferences` at the same time
- **THEN** exactly one preferences row exists afterwards

Tests: backend/tests/test_user_preferences_api.py::ConcurrentFirstVisitRace::test_concurrent_first_visit_ends_with_exactly_one_row

### Requirement: Preference reads normalize bad stored values without writing
The system SHALL normalize stored preferences on read without writing them back, and SHALL return them as a frozen DTO whose suggestions are a tuple copy.
Enforced: backend/templates_mgr/preferences.py::get_user_preferences, backend/templates_mgr/preferences.py::normalize_theme, backend/templates_mgr/preferences.py::normalize_chat_suggestions, backend/templates_mgr/preferences.py::normalize_default_block_gap_minutes

#### Scenario: Corrupt theme on read
- **WHEN** the stored theme is not `classic`, `strategic`, `light_premium` or `dark_4a`
- **THEN** the read returns `classic` and the stored value is unchanged

Tests: backend/tests/test_user_preferences_api.py::test_helper_normalizes_invalid_db_value_without_writing, backend/tests/test_user_preferences_api.py::test_normalize_theme_pure_function

#### Scenario: Corrupt gap on read
- **WHEN** the stored gap is not an int from 0 to 120 divisible by 5 (booleans, strings and floats included)
- **THEN** the read returns `10` and the stored value is unchanged

Tests: backend/tests/test_user_preferences_api.py::test_gap_normalization_is_strict, backend/tests/test_user_preferences_api.py::test_gap_default_and_corrupt_read_without_write

#### Scenario: Null or malformed suggestions
- **WHEN** the stored suggestions are null, not a list, or contain non-strings
- **THEN** the read returns the three default suggestions and the stored value is unchanged

Tests: backend/tests/test_user_preferences_api.py::test_helper_null_suggestions_resolve_to_defaults, backend/tests/test_user_preferences_api.py::test_helper_malformed_suggestions_fall_back_without_writing

#### Scenario: Valid stored suggestions
- **WHEN** the stored suggestions are a list of strings, including `[]` or more than the patch cap
- **THEN** the read trims entries, drops blank ones, keeps order, and keeps `[]` empty

Tests: backend/tests/test_user_preferences_api.py::test_helper_preserves_saved_order, backend/tests/test_user_preferences_api.py::test_helper_preserves_saved_empty_list, backend/tests/test_user_preferences_api.py::test_helper_trims_and_drops_empty_entries_without_writing, backend/tests/test_user_preferences_api.py::test_helper_returns_structurally_valid_over_cap_values_without_writing

#### Scenario: Immutable result
- **WHEN** a caller receives the preferences DTO
- **THEN** it is frozen and its suggestions tuple is not the ORM JSON list

Tests: backend/tests/test_user_preferences_api.py::test_helper_returns_frozen_dto_not_orm_instance, backend/tests/test_user_preferences_api.py::test_helper_suggestions_are_tuple_copy_not_jsonfield_alias

### Requirement: Patch user preferences
The system SHALL partially update `theme`, `chat_suggestions` and `default_block_gap_minutes` on `PATCH /api/user/preferences/`, ignore unknown keys, keep omitted fields, and respond `200` with the full normalized preferences object. Patching a field to its current value is a valid no-op.
Enforced: backend/templates_mgr/api.py::user_preferences

#### Scenario: Set the theme
- **WHEN** a user patches `theme` to a recognized id such as `dark_4a`
- **THEN** the response is `200` and the stored theme changes

Tests: backend/tests/test_user_preferences_api.py::test_patch_sets_theme, backend/tests/test_user_preferences_api.py::test_patch_sets_dark_4a_theme, backend/tests/test_user_preferences_api.py::test_patch_same_value_is_valid_noop

#### Scenario: Partial patch keeps other fields
- **WHEN** a user patches only one field
- **THEN** the other saved fields are unchanged, and unset suggestions still read as the defaults

Tests: backend/tests/test_user_preferences_api.py::test_patch_combined_theme_and_suggestions, backend/tests/test_user_preferences_api.py::test_theme_only_patch_preserves_saved_suggestions, backend/tests/test_user_preferences_api.py::test_theme_only_patch_with_null_suggestions_returns_defaults, backend/tests/test_user_preferences_api.py::test_suggestions_only_patch_preserves_theme

#### Scenario: Heal a corrupt theme
- **WHEN** the stored theme is invalid and the user patches `theme: "classic"`
- **THEN** the stored row now holds `classic`

Tests: backend/tests/test_user_preferences_api.py::test_patch_heals_corrupted_row

#### Scenario: Unknown keys
- **WHEN** the body has a valid field plus unknown keys such as `user_id` naming another user
- **THEN** the unknown keys are ignored and only the requesting user's preferences change

Tests: backend/tests/test_user_preferences_api.py::test_patch_unknown_field_alongside_valid_theme_is_accepted, backend/tests/test_user_preferences_api.py::test_gap_round_trip_sessions_pages_and_schedule_unchanged

### Requirement: Preference patch validation
The system SHALL validate every recognized preference field before writing anything. On any failure it SHALL return `400` keyed by the field and write nothing, creating no row on first use. A body with no recognized field SHALL return `400` with `errors.body = "No editable fields supplied."`.
Enforced: backend/templates_mgr/api.py::user_preferences, backend/templates_mgr/preferences.py::is_valid_default_block_gap_minutes

#### Scenario: Invalid theme
- **WHEN** `theme` is not a string or not one of `classic`, `strategic`, `light_premium`, `dark_4a`
- **THEN** the response is `400` with `errors.theme = "Invalid theme."`

Tests: backend/tests/test_user_preferences_api.py::test_patch_invalid_theme_returns_400, backend/tests/test_user_preferences_api.py::test_patch_non_string_theme_returns_structured_400

#### Scenario: Invalid suggestions
- **WHEN** `chat_suggestions` is not an array, has more than 8 entries, or has an entry that is not a string, is blank after trimming, or exceeds 120 characters
- **THEN** the response is `400` with `errors.chat_suggestions`

Tests: backend/tests/test_user_preferences_api.py::test_patch_non_array_suggestions_returns_400, backend/tests/test_user_preferences_api.py::test_patch_invalid_suggestion_entries_return_400

#### Scenario: Invalid suggestions with a valid theme
- **WHEN** a PATCH sends a valid theme and a blank suggestion
- **THEN** the response is `400` and neither the theme nor the suggestions change

Tests: backend/tests/test_user_preferences_api.py::test_combined_invalid_payload_writes_neither_field

#### Scenario: Valid suggestions are stored trimmed
- **WHEN** `chat_suggestions` is a valid array, including `[]` or 120-code-point entries
- **THEN** entries are stored trimmed with order and duplicates kept, and a re-sent list replaces rather than appends

Tests: backend/tests/test_user_preferences_api.py::test_patch_chat_suggestions_round_trip_trims_and_preserves_order, backend/tests/test_user_preferences_api.py::test_patch_empty_suggestions_is_valid_and_stays_empty, backend/tests/test_user_preferences_api.py::test_patch_accepts_120_code_point_emoji_boundary, backend/tests/test_user_preferences_api.py::test_restore_defaults_is_idempotent_replace_not_append

#### Scenario: Invalid gap with valid siblings
- **WHEN** a PATCH sends a valid theme, valid suggestions and a gap that is not an int from 0 to 120 divisible by 5
- **THEN** the response is `400` with `errors.default_block_gap_minutes`, neither theme nor suggestions change, and no row is created for a first-time user

Tests: backend/tests/test_user_preferences_api.py::test_gap_strict_validation_is_atomic

#### Scenario: Empty, unknown-only or malformed body
- **WHEN** the body is empty, has only unknown keys, is invalid JSON, or is not a JSON object
- **THEN** the response is `400` with an `errors.body` message

Tests: backend/tests/test_user_preferences_api.py::test_patch_empty_body_returns_400, backend/tests/test_user_preferences_api.py::test_patch_unknown_field_only_is_400, backend/tests/test_user_preferences_api.py::test_patch_invalid_json_returns_400, backend/tests/test_user_preferences_api.py::test_patch_non_object_body_returns_400

### Requirement: Preference responses are private and uncacheable
The system SHALL set `Cache-Control: private, no-store` on every response produced by the preferences view, including `400`, `409` and `413` errors. Decorator-produced `302` login redirects and `405` responses do not carry this header.
Enforced: backend/templates_mgr/api.py::_prefs_response, backend/templates_mgr/api.py::user_preferences

#### Scenario: Lock conflict on preferences
- **WHEN** a preferences PATCH cannot acquire the user write lock
- **THEN** the response is `409` with `code: "schedule_changed"` and `Cache-Control: private, no-store`, and the stored value is unchanged

Tests: backend/tests/test_user_preferences_api.py::test_gap_lock_conflict_has_private_header, backend/tests/test_schedule_mutations_sqlite.py::test_preferences_patch_under_independent_writer_reservation

#### Scenario: Oversized body
- **WHEN** a preferences PATCH body exceeds 100 KB
- **THEN** the response is `413` with `Cache-Control: private, no-store`

Tests: backend/tests/test_user_preferences_api.py::test_patch_oversized_body_returns_413_with_cache_control

#### Scenario: Decorator responses
- **WHEN** an anonymous client calls the endpoint or an authenticated client uses an unsupported method
- **THEN** the `302` or `405` response does not carry `Cache-Control: private, no-store`

Tests: backend/tests/test_user_preferences_api.py::test_unauthenticated_get_302_has_no_cache_control_header, backend/tests/test_user_preferences_api.py::test_unauthenticated_patch_302_has_no_cache_control_header, backend/tests/test_user_preferences_api.py::test_method_not_allowed_405_has_no_cache_control_header

### Requirement: Preferences are isolated per user
The system MUST read and write preferences only for the authenticated user.
Enforced: backend/templates_mgr/api.py::user_preferences

#### Scenario: Two users with different preferences
- **WHEN** user A patches their theme or suggestions
- **THEN** user B's preferences are unchanged

Tests: backend/tests/test_user_preferences_api.py::test_preferences_isolated_per_user, backend/tests/test_user_preferences_api.py::test_suggestions_are_isolated_per_user, backend/tests/test_user_preferences_api.py::test_patch_does_not_leak_across_users

### Requirement: Gap preference changes do not touch schedules
The system SHALL NOT change existing schedule blocks, schedule status or schedule revision when `default_block_gap_minutes` changes, and the new gap SHALL appear in the API and in page `ui_preferences` props across sessions.
Enforced: backend/templates_mgr/api.py::user_preferences

#### Scenario: Change gap with an existing schedule
- **WHEN** a user with an active schedule at revision 3 patches the gap to 20
- **THEN** the schedule keeps status `active`, revision 3 and the same blocks, and Settings, Schedule and Analytics props report gap 20

Tests: backend/tests/test_user_preferences_api.py::test_gap_round_trip_sessions_pages_and_schedule_unchanged

### Requirement: Settings page props
The system SHALL render `/settings/` (login required) as the Inertia `Settings` page with the user's templates, rules, travel rules, categories, normalized `ui_preferences` and schedule window. Preferences SHALL be resolved once per render, and the same theme SHALL be passed as `template_data.initial_theme`.
Enforced: backend/templates_mgr/views.py::settings_view

#### Scenario: Hard load with a saved theme
- **WHEN** a user with theme `strategic` loads `/settings/`
- **THEN** the HTML contains `data-theme="strategic"`

Tests: backend/tests/test_user_preferences_api.py::test_authenticated_hard_load_uses_persisted_theme

#### Scenario: Inertia request
- **WHEN** the Settings page is requested with `X-Inertia: true`
- **THEN** the props include `ui_preferences` and `schedule_window.time_zone`

Tests: backend/tests/test_user_preferences_api.py::test_settings_view_includes_ui_preferences_prop, backend/tests/test_user_preferences_api.py::test_settings_view_includes_schedule_time_zone

#### Scenario: List ordering in props
- **WHEN** the Settings page renders
- **THEN** templates are ordered by `type` and rules by `-priority, id`
