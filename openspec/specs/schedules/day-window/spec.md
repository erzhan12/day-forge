# schedules/day-window Specification

## Purpose
Each user has one schedule-settings row holding a working-day window (`day_start`-`day_end`) and an IANA time zone. This spec covers the settings model and its validation, the `GET`/`PATCH /api/user/schedule-settings/` endpoint, window parsing and clamping helpers, and how the saved time zone decides the user's local "today" for the root and login redirects. How block writes use the window is specified in `schedules/blocks`.

## Requirements

### Requirement: One settings row per user with defaults
The system SHALL keep at most one `UserScheduleSettings` row per user and create it on first use with window `06:00`-`23:00` and time zone `UTC`. Repeated lookups MUST NOT create more rows.
Enforced: backend/schedules/models.py::UserScheduleSettings.user, backend/schedules/window.py::get_schedule_settings

#### Scenario: First use
- **WHEN** settings are read for a user with no row
- **THEN** a row with `06:00`, `23:00` and `UTC` is created and returned

Tests: backend/tests/test_schedule_settings_model.py::TestGetScheduleWindow::test_default_window_created, backend/tests/test_schedule_settings_model.py::TestGetScheduleWindow::test_new_row_defaults_time_zone_to_utc, backend/tests/test_schedule_settings_model.py::TestGetScheduleWindow::test_get_or_create_idempotent

#### Scenario: Second row for the same user
- **WHEN** a second settings row is inserted for the same user
- **THEN** the database rejects it

Tests: backend/tests/test_schedule_settings_model.py::TestOneToOne::test_second_row_for_same_user_rejected

#### Scenario: Saved values
- **WHEN** a user has a saved custom window and time zone
- **THEN** the lookup returns those values

Tests: backend/tests/test_schedule_settings_model.py::TestGetScheduleWindow::test_returns_persisted_custom_window, backend/tests/test_schedule_settings_model.py::TestGetScheduleWindow::test_get_schedule_settings_includes_persisted_time_zone

### Requirement: Settings rows are always valid
The system MUST validate on every save that `day_start` and `day_end` lie on the five-minute grid with zero seconds, `day_start < day_end` on the same day, and `time_zone` is a valid IANA zone. The database SHALL also enforce `day_start < day_end`.
Enforced: backend/schedules/models.py::UserScheduleSettings.clean, backend/schedules/models.py::UserScheduleSettings.save, backend/schedules/models.py::UserScheduleSettings.Meta.constraints

#### Scenario: Invalid window on save
- **WHEN** a row is saved with an off-grid minute, non-zero seconds, or start equal to or after end
- **THEN** a validation error is raised and nothing is written

Tests: backend/tests/test_schedule_settings_model.py::TestInvalidModelRejection::test_full_clean_rejects_off_grid_start, backend/tests/test_schedule_settings_model.py::TestInvalidModelRejection::test_full_clean_rejects_seconds_on_start, backend/tests/test_schedule_settings_model.py::TestInvalidModelRejection::test_full_clean_rejects_start_after_end, backend/tests/test_schedule_settings_model.py::TestInvalidModelRejection::test_save_rejects_off_grid, backend/tests/test_schedule_settings_model.py::TestInvalidModelRejection::test_save_rejects_inverted_pair

#### Scenario: Invalid time zone on save
- **WHEN** a row is saved with a zone name that does not resolve
- **THEN** a validation error is raised and no row is written

Tests: backend/tests/test_schedule_settings_model.py::TestInvalidModelRejection::test_invalid_time_zone_is_rejected, backend/tests/test_schedule_settings_model.py::TestInvalidModelRejection::test_save_rejects_invalid_time_zone_without_writing_row

#### Scenario: Bulk insert bypassing save
- **WHEN** an inverted pair is bulk-created
- **THEN** the database check constraint rejects it

Tests: backend/tests/test_schedule_settings_model.py::TestCheckConstraint::test_bulk_create_inverted_pair_hits_db_constraint

### Requirement: Read schedule settings
The system SHALL return `GET /api/user/schedule-settings/` as `{day_start, day_end, time_zone}` with `HH:MM` times for the authenticated user, creating the default row on first use. Every response, including errors, MUST carry `Cache-Control: private, no-store`.
Enforced: backend/schedules/settings_api.py::schedule_settings, backend/schedules/settings_api.py::_settings_response

#### Scenario: First call
- **WHEN** a user with no row requests settings
- **THEN** the response is `{"day_start": "06:00", "day_end": "23:00", "time_zone": "UTC"}` with `private, no-store`

Tests: backend/tests/test_schedule_settings_api.py::test_get_first_call_returns_default_window

#### Scenario: Saved values
- **WHEN** a user with a saved window and non-UTC zone requests settings
- **THEN** the saved values are returned

Tests: backend/tests/test_schedule_settings_api.py::test_get_returns_saved_window, backend/tests/test_schedule_settings_api.py::test_get_returns_persisted_non_utc_time_zone

#### Scenario: First-use write contention
- **WHEN** creating the first row hits schedule write contention
- **THEN** the response is 409 `code: schedule_changed` with `private, no-store` and no row is created

Tests: backend/tests/test_schedule_settings_api.py::test_get_first_use_busy_conflict_is_controlled_and_private

### Requirement: Update schedule settings partially
The system SHALL accept `PATCH /api/user/schedule-settings/` with `day_start` and `day_end` together, `time_zone` alone, or all three, leaving omitted fields unchanged, and return the full saved settings. A first-time PATCH MUST create the row directly with the submitted values.
Enforced: backend/schedules/settings_api.py::schedule_settings

#### Scenario: Valid window
- **WHEN** a user patches a valid `day_start` and `day_end`
- **THEN** the response is 200 echoing the saved `HH:MM` values and the row is updated

Tests: backend/tests/test_schedule_settings_api.py::test_patch_valid_persists_and_echoes_normalized_window, backend/tests/test_schedule_settings_api.py::test_patch_updates_existing_row

#### Scenario: Time zone only
- **WHEN** a user patches only `time_zone`, then only the window
- **THEN** each PATCH keeps the fields it did not send

Tests: backend/tests/test_schedule_settings_api.py::test_patch_all_fields_and_timezone_only_are_partial_updates, backend/tests/test_schedule_settings_api.py::test_patch_first_time_with_time_zone_persists_zone_via_defaults

#### Scenario: Existing blocks untouched
- **WHEN** the time zone is changed on a user with blocks
- **THEN** the blocks keep their stored clock times

Tests: backend/tests/test_timezone_consistency.py::test_timezone_setting_change_keeps_existing_block_clock_times

### Requirement: Invalid settings updates change nothing
The system SHALL reject a PATCH with 400 and leave the stored row unchanged when the body is not a JSON object, is empty, sends only one window bound, has a bad window value, or has an invalid zone (`Must be a valid IANA time zone.`). All field errors are reported together.
Enforced: backend/schedules/settings_api.py::schedule_settings, backend/schedules/window.py::validate_window

#### Scenario: Missing bound or empty body
- **WHEN** the body is `{}` or contains only `day_start` or only `day_end`
- **THEN** the response is 400 naming each missing bound as `{field} is required.`

Tests: backend/tests/test_schedule_settings_api.py::test_patch_missing_field_returns_400_and_leaves_row_unchanged

#### Scenario: Bad values
- **WHEN** the window is malformed, off-grid or inverted, or the zone is invalid
- **THEN** the response is 400 with errors for every bad field and the row is unchanged

Tests: backend/tests/test_schedule_settings_api.py::test_patch_invalid_window_returns_400_and_leaves_row_unchanged, backend/tests/test_schedule_settings_api.py::test_patch_invalid_time_zone_has_stable_error, backend/tests/test_schedule_settings_api.py::test_patch_invalid_window_and_time_zone_reports_both_errors_and_keeps_row

#### Scenario: Bad body
- **WHEN** the body is invalid JSON or not an object
- **THEN** the response is 400 and the row is unchanged

Tests: backend/tests/test_schedule_settings_api.py::test_patch_invalid_json_returns_400_and_leaves_row_unchanged, backend/tests/test_schedule_settings_api.py::test_patch_non_object_body_returns_400_and_leaves_row_unchanged

### Requirement: Settings are private to each user
The system SHALL read and write only the authenticated user's settings row and MUST redirect anonymous requests to login.
Enforced: backend/schedules/settings_api.py::schedule_settings

#### Scenario: Two users
- **WHEN** one user patches their window or zone
- **THEN** another user's settings are unchanged and each GET returns its own values

Tests: backend/tests/test_schedule_settings_api.py::test_get_isolated_per_user, backend/tests/test_schedule_settings_api.py::test_patch_does_not_leak_across_users, backend/tests/test_schedule_settings_api.py::test_custom_time_zone_patch_does_not_leak_across_users, backend/tests/test_schedule_settings_model.py::TestMultiUserIsolation::test_custom_window_does_not_touch_other_users_default

#### Scenario: Anonymous request
- **WHEN** an unauthenticated client calls GET or PATCH
- **THEN** no settings data is returned or changed

Tests: backend/tests/test_schedule_settings_api.py::test_get_requires_auth, backend/tests/test_schedule_settings_api.py::test_patch_requires_auth

### Requirement: Window strings are strict HH:MM on the grid
The system SHALL accept a window bound only as a two-digit, zero-padded `HH:MM` string with minutes divisible by 5, and require `day_end` later than `day_start`; overnight windows MUST be rejected.
Enforced: backend/schedules/window.py::validate_window, backend/schedules/window.py::check_time_on_grid

#### Scenario: Valid pair
- **WHEN** `06:00` and `23:00` are validated
- **THEN** a window with those bounds is returned

Tests: backend/tests/test_schedule_window.py::test_validate_window_accepts_default_pair

#### Scenario: Non-canonical or off-grid
- **WHEN** a bound is not a string, is `6:00` or `06:5`, or is `06:07`
- **THEN** that bound gets `Must be an HH:MM string.`, `Use HH:MM format.` or `Must align to 5-minute granularity.`

Tests: backend/tests/test_schedule_window.py::test_validate_window_rejects_non_string, backend/tests/test_schedule_window.py::test_validate_window_rejects_non_canonical_single_digit_minute, backend/tests/test_schedule_window.py::test_validate_window_rejects_non_canonical_unpadded_minute, backend/tests/test_schedule_window.py::test_validate_window_rejects_off_grid, backend/tests/test_schedule_window.py::test_validate_window_rejects_non_hhmm

#### Scenario: Equal, inverted or overnight
- **WHEN** `day_end` is equal to or earlier than `day_start`
- **THEN** `day_end` gets `Must be later than day_start; overnight windows are not supported.`

Tests: backend/tests/test_schedule_window.py::test_validate_window_rejects_start_equals_end, backend/tests/test_schedule_window.py::test_validate_window_rejects_start_after_end, backend/tests/test_schedule_window.py::test_validate_window_rejects_overnight

#### Scenario: Seconds on a time value
- **WHEN** a time value with non-zero seconds or microseconds is checked against the grid
- **THEN** it is rejected with `Must not include seconds.`

Tests: backend/tests/test_schedule_window.py::test_check_time_on_grid_rejects_seconds, backend/tests/test_schedule_window.py::test_check_time_on_grid_rejects_microseconds

### Requirement: Clamping moves only the requested boundaries
The system SHALL clamp a requested start up to `day_start` and a requested end down to `day_end`, leave unrequested boundaries as they are, and return no interval when a requested boundary lies wholly past the opposite edge or the result is empty.
Enforced: backend/schedules/window.py::clamp_boundary

#### Scenario: Partial crossing
- **WHEN** an interval crossing a window edge is clamped with that boundary requested
- **THEN** it is cut to the edge

Tests: backend/tests/test_schedule_window.py::test_clamp_boundary_both_flags_partial_cross_clamps_to_boundary, backend/tests/test_schedule_window.py::test_clamp_boundary_fully_inside_unchanged

#### Scenario: One flag
- **WHEN** only the start or only the end is requested
- **THEN** the other boundary is not moved

Tests: backend/tests/test_schedule_window.py::test_clamp_boundary_single_start_flag_leaves_end_untouched, backend/tests/test_schedule_window.py::test_clamp_boundary_single_end_flag_leaves_start_untouched

#### Scenario: Fully outside
- **WHEN** the interval lies wholly outside the window, or a requested start is after `day_end`, or a requested end is before `day_start`
- **THEN** no interval is returned

Tests: backend/tests/test_schedule_window.py::test_clamp_boundary_fully_outside_returns_none, backend/tests/test_schedule_window.py::test_clamp_boundary_case_b_start_past_day_end_returns_none, backend/tests/test_schedule_window.py::test_clamp_boundary_case_b_end_before_day_start_returns_none

### Requirement: Stored time zones resolve safely
The system SHALL validate submitted zones strictly but resolve a stored zone leniently, falling back to UTC when it is missing or does not resolve.
Enforced: backend/schedules/window.py::validate_time_zone, backend/schedules/window.py::resolve_time_zone

#### Scenario: Valid and invalid submissions
- **WHEN** an IANA identifier and an invalid value are validated
- **THEN** the identifier resolves and the invalid value raises `Must be a valid IANA time zone.`

Tests: backend/tests/test_schedule_window.py::test_validate_time_zone_accepts_iana_identifiers, backend/tests/test_schedule_window.py::test_validate_time_zone_rejects_invalid_values

#### Scenario: Corrupt stored zone
- **WHEN** a stored zone string does not resolve
- **THEN** UTC is used

Tests: backend/tests/test_schedule_window.py::test_resolve_time_zone_falls_back_to_utc_by_identity

### Requirement: Today is the user's local date
The system SHALL compute an authenticated user's "today" from the current time in their saved zone, and redirect `/` and a successful login to `/schedule/{today}/`. An anonymous `/` request SHALL use the server date without looking up settings.
Enforced: backend/schedules/window.py::user_local_date, backend/schedules/views.py::root_redirect, backend/schedules/views.py::login_view

#### Scenario: East and west of UTC
- **WHEN** it is 20:00 UTC for an `Asia/Almaty` user, or 03:00 UTC for an `America/Los_Angeles` user
- **THEN** `/` and login redirect to the next or previous calendar date respectively

Tests: backend/tests/test_root_login_redirect.py::TestRootLoginRedirect::test_root_redirect_uses_user_local_date_east_of_utc, backend/tests/test_root_login_redirect.py::TestRootLoginRedirect::test_root_redirect_west_of_utc, backend/tests/test_root_login_redirect.py::TestRootLoginRedirect::test_login_post_redirects_to_user_local_date, backend/tests/test_root_login_redirect.py::TestRootLoginRedirect::test_login_post_redirects_to_user_local_date_west_of_utc

#### Scenario: Anonymous root
- **WHEN** an unauthenticated client requests `/`
- **THEN** it is redirected to a schedule date without resolving any user settings

Tests: backend/tests/test_root_login_redirect.py::TestRootLoginRedirect::test_root_redirect_anonymous_does_not_resolve_user_settings
