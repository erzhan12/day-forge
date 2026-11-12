# schedules/schedule-page Specification

## Purpose
`GET /schedule/{date}/` renders the Inertia `Schedule` page for one day of the signed-in user. This spec covers how the page reads an existing day, creates a missing day and the user's first-use policy rows, the props it sends (schedule, ordered blocks, categories, window, preferences, template and auto-draft flags, integration bootstrap), and its controlled 503 when first-use creation is contended. It also covers the shared owner-scoped day reader. Draft generation itself belongs to the AI capability.

## Requirements

### Requirement: Schedule page requires login and a valid date
The system SHALL redirect anonymous requests for `/schedule/{date}/` to login and return 400 `Invalid date format. Use YYYY-MM-DD.` for a date that is not ISO `YYYY-MM-DD`.
Enforced: backend/schedules/views.py::schedule_view

#### Scenario: Anonymous visit
- **WHEN** an unauthenticated client requests a schedule page
- **THEN** it is redirected to login

Tests: backend/tests/test_views.py::TestScheduleView::test_unauthenticated_redirects

#### Scenario: Bad date
- **WHEN** a signed-in user requests `/schedule/not-a-date/`
- **THEN** the response is 400

Tests: backend/tests/test_views.py::TestScheduleView::test_invalid_date_returns_400

### Requirement: Visiting a missing day creates it once
The system SHALL create a `draft` schedule for the user and date on the first page visit, together with any missing schedule settings, preferences and category catalog. Concurrent first visits MUST produce exactly one schedule and one row of each policy.
Enforced: backend/schedules/views.py::_create_schedule_page_rows, backend/schedules/views.py::schedule_view

#### Scenario: First visit
- **WHEN** a user opens a date that has no schedule
- **THEN** the page renders with status 200 and the schedule now exists

Tests: backend/tests/test_views.py::TestScheduleView::test_creates_schedule_if_missing, backend/tests/test_schedule_view_props.py::TestSharedScheduleDayReader::test_absent_day_still_bootstraps_through_the_page_view

#### Scenario: Two simultaneous first visits
- **WHEN** two requests open the same new date at once for a user with a matching template and a configured AI key
- **THEN** both render with 200, one schedule and one row of each policy exist, and exactly one response has `auto_draft_pending` true

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_two_first_visits_create_once_and_signal_once

#### Scenario: Existing day missing policy rows
- **WHEN** an existing schedule is opened by a user without settings, preferences or categories
- **THEN** the missing rows are created and the existing schedule is shown

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_existing_day_with_missing_policies_bootstraps_without_autodraft

### Requirement: Contended first-use creation returns 503
The system SHALL answer a page visit whose first-use creation cannot get the write lock, or that hits a SQLite locked/busy error, with plain-text 503 and `Retry-After: 1`, creating no rows.
Enforced: backend/schedules/views.py::schedule_view, backend/schedules/views.py::_schedule_unavailable_response

#### Scenario: Writer held elsewhere
- **WHEN** a new day or missing policy row must be created while another connection holds the SQLite writer
- **THEN** the response is 503 with `Retry-After: 1` and no schedule or policy row is created

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_schedule_get_creation_contention_returns_controlled_503, backend/tests/test_schedule_mutations_sqlite.py::test_missing_policy_under_writer_returns_controlled_503

### Requirement: Existing days are read from one snapshot without a writer
The system SHALL read an existing, fully bootstrapped day's schedule, blocks and policies in one read transaction without reserving the SQLite writer, so the page renders while another writer is active and never mixes two commits.
Enforced: backend/schedules/views.py::_read_schedule_page

#### Scenario: Concurrent writer
- **WHEN** an existing day is opened while another connection holds the writer, or commits a change between the schedule read and the block read
- **THEN** the page renders with 200 and its schedule revision and blocks come from the same snapshot

Tests: backend/tests/test_schedule_mutations_sqlite.py::test_existing_schedule_get_reads_during_independent_writer, backend/tests/test_schedule_mutations_sqlite.py::test_schedule_get_snapshot_stays_coherent_across_concurrent_commit

### Requirement: Schedule page props
The system SHALL render the `Schedule` component with `schedule` `{id, date, status, revision}`, the day's serialized `blocks` ordered by start time, sort order and id, the user's `categories`, `date`, `slot_type`, `schedule_window` `{start, end, time_zone}`, `ui_preferences` and `external_tasks_poll_interval`.
Enforced: backend/schedules/views.py::schedule_view, backend/schedules/serialization.py::serialize_schedule

#### Scenario: Block order
- **WHEN** a day has a 09:00 block created before an 08:00 block
- **THEN** `blocks` lists the 08:00 block first

Tests: backend/tests/test_schedule_view_props.py::TestSharedScheduleDayReader::test_page_still_reflects_the_shared_reader_block_ordering

#### Scenario: Window prop
- **WHEN** the user's settings are `08:00`-`21:00` in `Asia/Almaty`
- **THEN** `schedule_window` is `{"start": "08:00", "end": "21:00", "time_zone": "Asia/Almaty"}`

Tests: backend/tests/test_schedule_view_props.py::test_schedule_window_prop_includes_persisted_time_zone

#### Scenario: Poll interval
- **WHEN** `EXTERNAL_TASKS_POLL_INTERVAL_SECONDS` is set, including `0`
- **THEN** `external_tasks_poll_interval` carries that value

Tests: backend/tests/test_schedule_view_props.py::TestExternalTasksPollIntervalProp::test_passes_setting_to_schedule_props, backend/tests/test_schedule_view_props.py::TestExternalTasksPollIntervalProp::test_zero_disables_polling

### Requirement: Template slot and auto-draft signal
The system SHALL set `slot_type` to `weekend` for Saturday and Sunday and `weekday` otherwise, `has_template_for_type` to whether the user has a template of that type, and `auto_draft_pending` true only on the request that created the schedule when such a template exists and an AI key is configured.
Enforced: backend/schedules/views.py::schedule_view

#### Scenario: First visit with template and key
- **WHEN** a new day is opened by a user with a matching template while an AI key is set
- **THEN** `auto_draft_pending` is true

Tests: backend/tests/test_schedule_view_props.py::TestAutoDraftPending::test_true_on_first_visit_with_template_and_key

#### Scenario: No signal
- **WHEN** the day already existed, or no matching template exists, or no AI key is set
- **THEN** `auto_draft_pending` is false

Tests: backend/tests/test_schedule_view_props.py::TestAutoDraftPending::test_false_on_second_visit, backend/tests/test_schedule_view_props.py::TestAutoDraftPending::test_false_without_template, backend/tests/test_schedule_view_props.py::TestAutoDraftPending::test_false_without_api_key, backend/tests/test_schedule_mutations_sqlite.py::test_existing_day_with_missing_policies_bootstraps_without_autodraft

#### Scenario: Weekend date
- **WHEN** a Saturday is opened by a user with a weekend template
- **THEN** `slot_type` is `weekend` and `has_template_for_type` is true

Tests: backend/tests/test_schedule_view_props.py::TestAutoDraftPending::test_weekend_slot_picked_for_saturday

### Requirement: Integration bootstrap is user-scoped and lazy
The system SHALL include `integration_bootstrap` with a fresh `snapshot_id`, `user_id`, `date`, `time_zone`, which of Apple, Google, Todoist and Habitica the user has connected, and the user's travel rules. It MUST contain only the requesting user's data and SHALL be omitted and not computed on partial reloads that do not ask for it.
Enforced: backend/schedules/views.py::_integration_bootstrap, backend/schedules/views.py::schedule_view

#### Scenario: Full visit
- **WHEN** a user opens the page while another user has connected accounts and rules
- **THEN** the bootstrap shows only this user's connections and rules, and a later full visit returns a new snapshot reflecting changes

Tests: backend/tests/test_integration_bootstrap.py::test_schedule_bootstrap_is_user_scoped_and_refreshed_on_next_full_visit

#### Scenario: Partial reload
- **WHEN** an Inertia partial reload asks only for `schedule`, `blocks` and `date`
- **THEN** `integration_bootstrap` is absent and its builder is not called

Tests: backend/tests/test_integration_bootstrap.py::test_partial_schedule_reload_omits_and_does_not_evaluate_bootstrap

### Requirement: Shared day reader is owner-scoped and read-only
The system SHALL provide `read_schedule_day(user, date)` returning the user's schedule and its blocks ordered by start time, sort order and id, or nothing when absent. It MUST NOT create rows and MUST NOT return another user's schedule.
Enforced: backend/schedules/reads.py::read_schedule_day

#### Scenario: Absent day
- **WHEN** the user has no schedule for the date
- **THEN** nothing is returned and no row is created

Tests: backend/tests/test_reads.py::test_absent_day_returns_none_without_creating_rows

#### Scenario: Another user's day
- **WHEN** only another user has a schedule on that date
- **THEN** nothing is returned

Tests: backend/tests/test_reads.py::test_owner_scoping_excludes_another_users_schedule_on_the_same_date

#### Scenario: Owned day
- **WHEN** the user has a schedule with blocks
- **THEN** the schedule and its deterministically ordered blocks are returned

Tests: backend/tests/test_reads.py::test_returns_owned_schedule_and_blocks, backend/tests/test_reads.py::test_blocks_are_deterministically_ordered
