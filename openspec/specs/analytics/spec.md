# analytics Specification

## Purpose
Per-day analytics and daily review for a user's schedule. It covers block statistics (planned, completed and skipped counts, completion ratio and category minutes), the reviewed snapshot frozen when an active day is marked reviewed, editable review notes, the completion streak, and the props of the Inertia analytics page. All reads and writes are scoped to the requesting user.

## Requirements

### Requirement: Daily block statistics
The system SHALL compute a day's statistics from its blocks: `planned_count` counts every block, `completed_count` counts blocks with `is_completed`, and the category maps sum `end_time - start_time` in whole minutes per category, with the completed map limited to completed blocks.
Enforced: backend/analytics/services.py::compute_review_stats, backend/analytics/services.py::_duration_minutes

#### Scenario: Mixed past day
- **WHEN** a past schedule has completed and uncompleted blocks
- **THEN** `planned_count` equals the block count and `completed_count` equals the completed block count

Tests: backend/tests/test_analytics_services.py::TestComputeReviewStats::test_mixed_past_day, backend/tests/test_analytics_services.py::TestComputeReviewStats::test_all_completed_past_day

#### Scenario: Category minutes
- **WHEN** a past day has completed work blocks of 60 and 90 minutes and an uncompleted 30-minute health block
- **THEN** planned minutes are work 150 and health 30, and completed minutes are work 150 and health 0

Tests: backend/tests/test_analytics_services.py::TestComputeReviewStats::test_category_aggregates_sum_correctly

### Requirement: Stable category map shape
The system MUST include every category of the user's ordered catalog in both category-minute maps, defaulting to 0, and SHALL count a block whose category slug is not in the catalog toward the sink category.
Enforced: backend/analytics/services.py::compute_review_stats

#### Scenario: Empty schedule
- **WHEN** a schedule has no blocks
- **THEN** all counts are 0 and both maps contain every catalog category with value 0

Tests: backend/tests/test_analytics_services.py::TestComputeReviewStats::test_empty_schedule_is_rest_day

#### Scenario: Unknown block category
- **WHEN** a block has a slug that is no longer in the user's catalog
- **THEN** its minutes are added to the sink category and the unknown slug is absent from the map

Tests: backend/tests/test_categories.py::TestAnalyticsFold::test_unknown_block_slug_folds_into_sink_not_keyerror

### Requirement: Today-aware skipped count
The system SHALL count an uncompleted block as skipped on a past day; on the user's local today only when its `end_time` is strictly before the current local time; and never on a future day.
Enforced: backend/analytics/services.py::compute_review_stats

#### Scenario: Past day
- **WHEN** a past day's blocks are all uncompleted
- **THEN** every block is counted as skipped

Tests: backend/tests/test_analytics_services.py::TestComputeReviewStats::test_all_uncompleted_past_day

#### Scenario: Today
- **WHEN** statistics are computed for today and some uncompleted blocks have not ended yet
- **THEN** only the uncompleted blocks that already ended are counted as skipped

Tests: backend/tests/test_analytics_services.py::TestComputeReviewStats::test_today_only_ended_blocks_skipped, backend/tests/test_analytics_services.py::TestComputeReviewStats::test_today_all_ended_uncompleted_are_skipped

#### Scenario: User time zone defines today
- **WHEN** the analytics page or mark-reviewed computes statistics
- **THEN** the current time used for the skip rule is the user's local time in their saved time zone, not the server zone

Tests: backend/tests/test_analytics_views.py::TestAnalyticsWiringUsesUserTimezone::test_skip_boundary_wiring_passes_user_local_now, backend/tests/test_analytics_views.py::TestMarkReviewedUsesUserTimezone::test_freeze_uses_user_local_day_east_of_utc, backend/tests/test_analytics_views.py::TestMarkReviewedUsesUserTimezone::test_freeze_uses_user_local_day_west_of_utc

### Requirement: Completion ratio
The system SHALL report the completion ratio as `completed_count / planned_count`, and as null when `planned_count` is 0 so a rest day is distinguishable from 0% completion.
Enforced: backend/analytics/models.py::DailyReview.completion_rate, backend/analytics/views.py::_review_to_dict

#### Scenario: Partial completion
- **WHEN** a review has 2 of 4 blocks completed
- **THEN** the completion ratio is 0.5

Tests: backend/tests/test_analytics_models.py::TestCompletionRate::test_partial_completion, backend/tests/test_analytics_models.py::TestCompletionRate::test_full_completion

#### Scenario: Nothing planned
- **WHEN** `planned_count` is 0
- **THEN** the completion ratio is null

Tests: backend/tests/test_analytics_models.py::TestCompletionRate::test_zero_planned_returns_none

### Requirement: Snapshot currency
The system SHALL treat a stored review as the current frozen snapshot only when the schedule status is `reviewed`, the review exists, and its `reviewed_revision` is non-null and equal to the schedule revision. Otherwise statistics MUST come from current blocks.
Enforced: backend/analytics/services.py::is_review_snapshot_current

#### Scenario: Revision or status mismatch
- **WHEN** a review's tag differs from the schedule revision, the tag is null, the review is missing, or the schedule is not reviewed
- **THEN** the snapshot is not current

Tests: backend/tests/test_analytics_services.py::test_review_snapshot_current_requires_status_and_revision

### Requirement: Freezing a review snapshot
The system SHALL freeze a snapshot by computing current statistics and upserting the schedule's single `DailyReview` with those aggregates and the given `reviewed_revision`, preserving existing notes.
Enforced: backend/analytics/services.py::freeze_review_snapshot, backend/analytics/models.py::DailyReview

#### Scenario: Repeated freeze
- **WHEN** a snapshot is frozen twice for the same schedule after notes were saved
- **THEN** the same row is updated and the notes are kept

Tests: backend/tests/test_analytics_services.py::TestFreezeReviewSnapshot::test_idempotent_preserves_notes

### Requirement: Analytics page access
The system SHALL serve `GET /analytics/{date}/` only to a logged-in user for a schedule they own dated on or before their local today; an invalid date or future date MUST return a plain-text 400 and a missing schedule 404, without creating a schedule.
Enforced: backend/analytics/views.py::analytics_view

#### Scenario: Missing schedule
- **WHEN** the user has no schedule on the requested date
- **THEN** the response is 404

Tests: backend/tests/test_analytics_views.py::TestAnalyticsView::test_404_on_missing_schedule

#### Scenario: Invalid or future date
- **WHEN** the date is not `YYYY-MM-DD` or is after the user's local today
- **THEN** the response is 400

Tests: backend/tests/test_analytics_views.py::TestAnalyticsView::test_400_on_invalid_date_format, backend/tests/test_analytics_views.py::TestAnalyticsView::test_400_on_future_date, backend/tests/test_analytics_views.py::TestAnalyticsFutureGateUsesUserTimezone::test_rejects_user_local_tomorrow, backend/tests/test_analytics_views.py::TestAnalyticsFutureGateUsesUserTimezone::test_west_of_utc_rejects_utc_today_as_future

#### Scenario: Local today east of UTC
- **WHEN** the requested date is the user's local today but tomorrow in UTC
- **THEN** the page renders with 200

Tests: backend/tests/test_analytics_views.py::TestAnalyticsFutureGateUsesUserTimezone::test_allows_user_local_today_east_of_utc

### Requirement: Analytics page review data
The page SHALL show the stored aggregates with `snapshot_kind: frozen` when the snapshot is current, and otherwise statistics computed in memory with `snapshot_kind: current`. GET MUST NOT create or update `DailyReview`; it shows stored notes and `reviewed_revision` when a row exists.
Enforced: backend/analytics/views.py::analytics_view, backend/analytics/views.py::_review_to_dict

#### Scenario: Active day without a review row
- **WHEN** an active day with no review is viewed, blocks change, and it is viewed again
- **THEN** both responses show current counts with `id` and `updated_at` null and no review row is created

Tests: backend/tests/test_analytics_views.py::TestAnalyticsView::test_recomputes_on_active_schedule, backend/tests/test_analytics_views.py::TestAnalyticsView::test_warm_get_does_not_write_database

#### Scenario: Reviewed day with a current snapshot
- **WHEN** a reviewed day with a matching snapshot is viewed
- **THEN** the stored snapshot and notes are shown with `snapshot_kind: frozen` and an unchanged `updated_at`

Tests: backend/tests/test_analytics_views.py::TestAnalyticsView::test_frozen_on_reviewed_schedule

#### Scenario: Reviewed day with a stale or missing snapshot
- **WHEN** a reviewed day's snapshot tag does not match its revision, or it has no review row
- **THEN** current statistics are shown with `snapshot_kind: current`, the stored notes and tag are echoed, and nothing is written

Tests: backend/tests/test_analytics_views.py::TestAnalyticsView::test_stale_reviewed_snapshot_uses_current_stats_without_writing, backend/tests/test_analytics_views.py::TestAnalyticsView::test_back_compat_recomputes_reviewed_without_row

### Requirement: Category minutes folded for display
The page SHALL return category-minute maps keyed by exactly the user's current catalog, adding minutes under unknown keys to the sink category and treating non-numeric or boolean values as 0, without changing stored data.
Enforced: backend/analytics/views.py::_normalized_category_minutes

#### Scenario: Stale persisted keys
- **WHEN** a stored map contains a deleted slug and malformed values
- **THEN** the deleted slug's minutes are added to the sink and malformed values count as 0

Tests: backend/tests/test_categories.py::TestAnalyticsFold::test_normalized_minutes_folds_stale_keys, backend/tests/test_categories.py::TestAnalyticsFold::test_normalized_minutes_coerces_malformed

### Requirement: Analytics page props
The page SHALL render the `Analytics` Inertia component with `review`, `streak` (`current`, `threshold`, `window_days`), `schedule` (`id`, `date`, `status`, `revision`), the day's serialized `blocks`, `categories`, `date`, `ui_preferences` and `schedule_window` including the saved time zone.
Enforced: backend/analytics/views.py::analytics_view, backend/analytics/views.py::_streak_payload

#### Scenario: Props present
- **WHEN** an existing past day is viewed
- **THEN** the props include the blocks, the streak payload and the persisted time zone in `schedule_window`

Tests: backend/tests/test_analytics_views.py::TestAnalyticsView::test_forwards_blocks_for_skipped_panel, backend/tests/test_analytics_views.py::TestAnalyticsView::test_includes_streak_payload, backend/tests/test_analytics_views.py::test_analytics_window_prop_includes_persisted_time_zone

### Requirement: Consistent analytics capture
The page MUST read the schedule, blocks, review and streak inside one transaction holding the user's row lock, so the revision and blocks come from the same capture as schedule writers.
Enforced: backend/analytics/views.py::analytics_view

#### Scenario: Write after capture
- **WHEN** a schedule write commits after the analytics data was captured
- **THEN** the page props keep the revision and blocks from the earlier capture

Tests: backend/tests/test_analytics_views.py::test_analytics_snapshot_keeps_revision_and_blocks_from_same_capture

### Requirement: Mark an active day reviewed
On `POST /api/analytics/schedules/{date}/mark-reviewed/` for an active day, the system SHALL require a valid `expected_revision`, freeze statistics tagged with the next revision, save optional notes, set status `reviewed`, advance the revision once and return the review with the mutation snapshot.
Enforced: backend/analytics/views.py::mark_reviewed

#### Scenario: Active day reviewed
- **WHEN** an active day is marked reviewed with its current revision
- **THEN** the response is 200 with `snapshot_kind: frozen`, status is `reviewed`, and `reviewed_revision` equals the new revision

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_active_to_reviewed_persists_and_flips, backend/tests/test_ai_revision.py::test_review_revision_retry_and_notes

#### Scenario: Notes and extra fields
- **WHEN** the body contains `notes` and unknown fields
- **THEN** the notes are stored and unknown fields are ignored; an empty body is accepted

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_optional_notes_persisted_on_active_to_reviewed, backend/tests/test_analytics_views.py::TestMarkReviewed::test_ignores_extra_fields, backend/tests/test_analytics_views.py::TestMarkReviewed::test_empty_body_accepted_on_active

#### Scenario: Invalid active-path body
- **WHEN** the active-path body is malformed JSON or has invalid encoding
- **THEN** the response is 400 and nothing is frozen

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_invalid_json_on_active_path_400s, backend/tests/test_http_json.py::test_active_review_rejects_invalid_encoding_without_freezing

#### Scenario: Missing or invalid revision
- **WHEN** an active day is posted without `expected_revision` or with a non-integer, boolean or negative value
- **THEN** the response is 409 with `code: schedule_changed`

Tests: backend/tests/test_ai_revision.py::test_ai_and_active_review_require_valid_revision

#### Scenario: Obsolete revision
- **WHEN** an active day is posted with an `expected_revision` that no longer matches the schedule revision
- **THEN** the response is 409 and the day is not reviewed

#### Scenario: Failure rolls back
- **WHEN** the status change fails after the snapshot is written
- **THEN** the status, revision and review row are rolled back

Tests: backend/tests/test_ai_revision.py::test_review_failure_rolls_back_review_status_and_revision

### Requirement: Mark-reviewed guards and ordering
The endpoint SHALL reject a body over the size limit with 413, an invalid date with 400 and a missing or foreign schedule with 404 before locking; under the User and Schedule locks it MUST refuse a draft day with 400 before parsing the body.
Enforced: backend/analytics/views.py::mark_reviewed

#### Scenario: Draft day
- **WHEN** the day's status is `draft`
- **THEN** the response is 400 and no review row is created

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_400_on_draft_schedule

#### Scenario: Oversized body
- **WHEN** the body exceeds the size limit, including on a reviewed retry
- **THEN** the response is 413

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_oversized_body_returns_413, backend/tests/test_http_json.py::test_reviewed_retry_still_applies_early_body_limit

#### Scenario: Missing or foreign schedule
- **WHEN** the user has no schedule on the date, even if another user does
- **THEN** the response is 404 with `{"errors": {"detail": "Not found."}}`

#### Scenario: Schedule row lock
- **WHEN** an active day is marked reviewed
- **THEN** the schedule row is selected for update

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_locks_parent_schedule_row

### Requirement: Reviewed retry is stable
For a day already `reviewed` under lock, mark-reviewed SHALL skip body parsing and revision checks, ignore body notes, and return the current snapshot unchanged; if the snapshot is missing or stale it MUST rebuild it at the existing revision, keeping notes and not advancing the revision.
Enforced: backend/analytics/views.py::mark_reviewed

#### Scenario: Retry with a current snapshot
- **WHEN** a reviewed day is posted again, with any body including malformed JSON or different notes
- **THEN** the response is 200 with the same snapshot and `updated_at`, and stored notes are unchanged

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_idempotent_returns_same_snapshot_unchanged_updated_at, backend/tests/test_analytics_views.py::TestMarkReviewed::test_idempotent_tolerates_malformed_body_on_reviewed, backend/tests/test_analytics_views.py::TestMarkReviewed::test_idempotent_ignores_different_notes_on_reviewed, backend/tests/test_http_json.py::test_reviewed_retry_skips_parser

#### Scenario: Repair a stale or missing snapshot
- **WHEN** a reviewed day has a stale-tagged or missing review and is posted again
- **THEN** the snapshot is rebuilt from current blocks with `reviewed_revision` equal to the unchanged schedule revision, and notes are preserved

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_repeat_post_repairs_stale_reviewed_snapshot_without_revision_bump, backend/tests/test_analytics_views.py::TestMarkReviewed::test_repeat_post_recovers_missing_review_without_revision_bump

#### Scenario: Concurrent review committed first
- **WHEN** another request reviewed the day between the ownership check and the lock
- **THEN** the existing snapshot is returned without refreezing

Tests: backend/tests/test_analytics_views.py::TestMarkReviewed::test_under_lock_recheck_skips_recompute_when_already_reviewed

### Requirement: Notes validation
Notes writes SHALL require a JSON object body with a `notes` string of at most 2000 characters; a missing, non-string or longer value MUST return 400, an empty string clears notes, and other fields are ignored. Mark-reviewed applies the same rule but treats `notes` as optional.
Enforced: backend/analytics/views.py::_validate_notes, backend/analytics/views.py::NOTES_MAX_CHARS

#### Scenario: Invalid notes body
- **WHEN** the notes PATCH body is empty, malformed JSON, or has notes over 2000 characters
- **THEN** the response is 400

Tests: backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_empty_body_400, backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_invalid_json_400, backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_notes_too_long_400

#### Scenario: Non-string notes
- **WHEN** `notes` is present but is not a string
- **THEN** the response is 400 with an error on `notes`

#### Scenario: Oversized body
- **WHEN** the notes PATCH body exceeds the size limit
- **THEN** the response is 413

Tests: backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_oversized_body_413

#### Scenario: Extra fields ignored
- **WHEN** the body also contains aggregate or id fields
- **THEN** only notes change

Tests: backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_other_fields_ignored

### Requirement: Saving notes by date
`PATCH /api/analytics/schedules/{date}/notes/` SHALL save notes on the user's existing schedule for that date under the User then Schedule lock, lazily creating `DailyReview`, without changing aggregates, `reviewed_revision` or the schedule revision; a missing or foreign schedule MUST return 404.
Enforced: backend/analytics/views.py::update_schedule_notes, backend/analytics/views.py::_write_notes, backend/common/middleware.py::InertiaIdentityMiddleware

#### Scenario: First notes save
- **WHEN** notes are saved for an active day with no review row
- **THEN** a review row is created with null `reviewed_revision`, the response uses current statistics with `snapshot_kind: current`, and the schedule revision is unchanged

Tests: backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_date_route_lazily_creates_notes_without_schedule_revision

#### Scenario: Another user's date
- **WHEN** a user saves notes for a date where only another user has a schedule
- **THEN** the response is 404 and no review row is created

Tests: backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_date_route_is_user_owned

#### Scenario: Session account changed
- **WHEN** the `X-Schedule-User` header does not match the logged-in user
- **THEN** the shared identity middleware returns 401 with `code: session_invalid` and nothing is saved

Tests: backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_date_route_rejects_changed_session_header

### Requirement: Saving notes by review id
`PATCH /api/analytics/reviews/{pk}/notes/` SHALL update notes on an existing review owned by the user through the same locked writer, never creating a row and not advancing the schedule revision; a missing or foreign review MUST return 404.
Enforced: backend/analytics/views.py::update_review_notes, backend/analytics/views.py::_write_notes

#### Scenario: Owner updates notes
- **WHEN** the owner patches notes on their review
- **THEN** the response is 200, notes are stored and the schedule revision is unchanged

Tests: backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_updates_notes, backend/tests/test_ai_revision.py::test_review_revision_retry_and_notes

#### Scenario: Foreign review
- **WHEN** another user patches the review
- **THEN** the response is 404 and the notes are unchanged

Tests: backend/tests/test_analytics_views.py::TestUpdateReviewNotes::test_cross_user_404

### Requirement: Completion streak
The system SHALL count consecutive days backward from the day before the user's local today with a completion ratio at or above `ANALYTICS_STREAK_THRESHOLD`, stopping at a day with no schedule or a ratio below the threshold. It MUST NOT walk more than `ANALYTICS_STREAK_WINDOW_DAYS` days.
Enforced: backend/analytics/services.py::compute_streak

#### Scenario: No history
- **WHEN** the user has no schedules
- **THEN** the streak is 0

Tests: backend/tests/test_analytics_services.py::TestComputeStreak::test_cold_start_no_schedules

#### Scenario: Consecutive days and breaks
- **WHEN** consecutive past days meet the threshold until a gap day or a below-threshold day
- **THEN** the streak counts only the qualifying days more recent than the break

Tests: backend/tests/test_analytics_services.py::TestComputeStreak::test_five_consecutive_above_threshold, backend/tests/test_analytics_services.py::TestComputeStreak::test_gap_day_breaks_streak, backend/tests/test_analytics_services.py::TestComputeStreak::test_below_threshold_breaks

#### Scenario: Window cap
- **WHEN** there are more qualifying days than the window
- **THEN** the streak equals the window size

Tests: backend/tests/test_analytics_services.py::TestComputeStreak::test_window_caps_streak

#### Scenario: Anchored to the user's local today
- **WHEN** the analytics page computes the streak
- **THEN** it uses the user's local today, regardless of the viewed date

Tests: backend/tests/test_analytics_views.py::TestAnalyticsWiringUsesUserTimezone::test_streak_wiring_passes_user_local_today

### Requirement: Streak day evaluation
A schedule with no blocks SHALL be skipped without breaking the streak. A day with blocks MUST use the stored ratio only when its snapshot is current; otherwise the ratio is computed from current blocks without writing a review.
Enforced: backend/analytics/services.py::compute_streak

#### Scenario: Rest day
- **WHEN** a day in the streak has a schedule with no blocks, with or without a review row
- **THEN** it is skipped and does not break the streak

Tests: backend/tests/test_analytics_services.py::TestComputeStreak::test_zero_block_day_skips_without_breaking, backend/tests/test_analytics_services.py::TestComputeStreak::test_empty_day_with_review_skips_without_breaking

#### Scenario: Reviewed day with a current snapshot
- **WHEN** a reviewed day's snapshot tag matches its revision
- **THEN** the stored ratio is used even if current blocks differ

Tests: backend/tests/test_analytics_services.py::TestComputeStreak::test_reviewed_day_uses_frozen_snapshot

#### Scenario: Unreviewed, stale or missing snapshot
- **WHEN** a day is active or draft, its reviewed snapshot is stale, or it has no review row
- **THEN** the ratio is computed from current blocks and no review row is created or changed

Tests: backend/tests/test_analytics_services.py::TestComputeStreak::test_unreviewed_day_ignores_persisted_review, backend/tests/test_analytics_services.py::TestComputeStreak::test_stale_reviewed_day_uses_current_blocks, backend/tests/test_analytics_services.py::TestComputeStreak::test_uncompleting_reviewed_day_uses_current_blocks, backend/tests/test_analytics_services.py::TestComputeStreak::test_on_the_fly_recompute_when_no_review_row

#### Scenario: Constant query cost
- **WHEN** the streak is computed over many days
- **THEN** exactly two queries are issued, one for schedules with reviews and one for their blocks

Tests: backend/tests/test_analytics_services.py::TestComputeStreak::test_uses_constant_query_count_regardless_of_streak_length

### Requirement: Streak settings validated at import
Settings MUST raise `ValueError` at import when `ANALYTICS_STREAK_THRESHOLD` (default 0.8) is outside [0.0, 1.0] or `ANALYTICS_STREAK_WINDOW_DAYS` (default 30) is not positive.
Enforced: backend/day_forge/settings.py::ANALYTICS_STREAK_THRESHOLD, backend/day_forge/settings.py::ANALYTICS_STREAK_WINDOW_DAYS

#### Scenario: Valid threshold values
- **WHEN** the threshold is unset, 0.5, 0.0 or 1.0
- **THEN** settings load with that value, 0.8 by default

Tests: backend/tests/test_settings_validation.py::TestStreakThresholdValidation::test_valid_default, backend/tests/test_settings_validation.py::TestStreakThresholdValidation::test_valid_explicit, backend/tests/test_settings_validation.py::TestStreakThresholdValidation::test_valid_boundaries

#### Scenario: Invalid threshold
- **WHEN** the threshold is above 1.0 or negative
- **THEN** importing settings raises `ValueError`

Tests: backend/tests/test_settings_validation.py::TestStreakThresholdValidation::test_above_one_raises, backend/tests/test_settings_validation.py::TestStreakThresholdValidation::test_negative_raises

#### Scenario: Valid window values
- **WHEN** the window is unset or a positive integer
- **THEN** settings load with that value, 30 by default

Tests: backend/tests/test_settings_validation.py::TestStreakWindowValidation::test_valid_default, backend/tests/test_settings_validation.py::TestStreakWindowValidation::test_valid_explicit

#### Scenario: Invalid window
- **WHEN** the window is zero or negative
- **THEN** importing settings raises `ValueError`

Tests: backend/tests/test_settings_validation.py::TestStreakWindowValidation::test_zero_raises, backend/tests/test_settings_validation.py::TestStreakWindowValidation::test_negative_raises

### Requirement: One review per schedule
The system SHALL store at most one `DailyReview` per schedule and MUST delete it when its schedule is deleted.
Enforced: backend/analytics/models.py::DailyReview.schedule

#### Scenario: Schedule deleted
- **WHEN** a schedule with a review is deleted
- **THEN** its review is deleted with it

### Requirement: Review admin keeps aggregates read-only
The Django admin for `DailyReview` SHALL show aggregates, revision tag and timestamps as read-only fields, and list the completion ratio as a whole percentage or `—` when nothing was planned.
Enforced: backend/analytics/admin.py::DailyReviewAdmin

#### Scenario: Admin list
- **WHEN** a staff user opens the review list
- **THEN** each row shows counts, the completion percentage and a notes excerpt of at most 80 characters
