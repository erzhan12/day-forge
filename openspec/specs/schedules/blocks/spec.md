# schedules/blocks Specification

## Purpose
A schedule is one user's plan for one calendar date, holding time blocks and a draft/active/reviewed status. This spec covers the schedule status lifecycle, creating, editing, completing, deleting and reordering blocks, and the interval rules every write must satisfy: time format, the five-minute grid, start before end, no overlap and the user's day window. It also covers per-user ownership, the block wire format and read-only admin access. Revisions, write locking, undo/restore, categories and AI drafting are specified elsewhere.

## Requirements

### Requirement: One schedule per user and date
The system MUST store at most one `Schedule` per (user, date); different users MAY each have a schedule on the same date. Schedules list newest date first.
Enforced: backend/schedules/models.py::Schedule.Meta.constraints, backend/schedules/models.py::Schedule.Meta.ordering

#### Scenario: Duplicate day for the same user
- **WHEN** a second schedule is inserted for a user and date that already has one
- **THEN** the database rejects it with an integrity error

Tests: backend/tests/test_models.py::TestSchedule::test_unique_user_date

#### Scenario: Same date for another user
- **WHEN** another user creates a schedule on the same date
- **THEN** the insert succeeds

Tests: backend/tests/test_models.py::TestSchedule::test_same_date_different_users

#### Scenario: Default ordering
- **WHEN** a user's schedules are listed without an explicit order
- **THEN** the later date comes first

Tests: backend/tests/test_models.py::TestSchedule::test_ordering

### Requirement: New schedules start as draft
The system SHALL create every schedule with status `draft`; the only statuses are `draft`, `active` and `reviewed`.
Enforced: backend/schedules/models.py::Schedule.status, backend/schedules/models.py::Schedule.Status

#### Scenario: Fresh schedule
- **WHEN** a schedule is created without a status
- **THEN** its status is `draft`

Tests: backend/tests/test_models.py::TestSchedule::test_create

### Requirement: Forward edits promote the schedule to active
The system SHALL flip a schedule from `draft` or `reviewed` to `active` when a block create, from-event create, delete, or a PATCH or reorder that changes at least one block is accepted. The flip MUST be a conditional database update so a stale in-memory status cannot skip it.
Enforced: backend/schedules/models.py::Schedule.mark_active_on_edit, backend/schedules/api.py::_create_block

#### Scenario: Draft becomes active
- **WHEN** `mark_active_on_edit` runs on a draft or reviewed schedule
- **THEN** the stored and in-memory status become `active` and it returns true

Tests: backend/tests/test_status_flow.py::TestMarkActiveOnEdit::test_flips_draft_to_active, backend/tests/test_status_flow.py::TestMarkActiveOnEdit::test_flips_reviewed_to_active

#### Scenario: Already active
- **WHEN** `mark_active_on_edit` runs on an active schedule
- **THEN** nothing changes and it returns false

Tests: backend/tests/test_status_flow.py::TestMarkActiveOnEdit::test_no_op_when_active

#### Scenario: Stale instance after a concurrent review
- **WHEN** the in-memory schedule says `active` but the stored row was changed to `reviewed`
- **THEN** the stored row is flipped back to `active`

Tests: backend/tests/test_status_flow.py::TestMarkActiveOnEdit::test_stale_instance_recovery

#### Scenario: Block endpoints flip draft and reviewed days
- **WHEN** a create, from-event create or DELETE, or a PATCH or reorder that changes a block, succeeds on a draft or reviewed day
- **THEN** the schedule status is `active`

Tests: backend/tests/test_status_flow.py::TestForwardMutationsFlipStatus::test_create_block_flips, backend/tests/test_status_flow.py::TestForwardMutationsFlipStatus::test_create_block_from_event_flips, backend/tests/test_status_flow.py::TestForwardMutationsFlipStatus::test_patch_block_flips, backend/tests/test_status_flow.py::TestForwardMutationsFlipStatus::test_delete_block_flips, backend/tests/test_status_flow.py::TestForwardMutationsFlipStatus::test_reorder_flips, backend/tests/test_status_flow.py::TestReviewedUnfreezesOnEdit::test_create_block_flips_reviewed_to_active, backend/tests/test_status_flow.py::TestReviewedUnfreezesOnEdit::test_create_block_from_event_flips_reviewed_to_active, backend/tests/test_status_flow.py::TestReviewedUnfreezesOnEdit::test_patch_block_flips_reviewed_to_active, backend/tests/test_status_flow.py::TestReviewedUnfreezesOnEdit::test_delete_block_flips_reviewed_to_active, backend/tests/test_status_flow.py::TestReviewedUnfreezesOnEdit::test_reorder_flips_reviewed_to_active

#### Scenario: Unchanged PATCH or reorder
- **WHEN** a PATCH or reorder resubmits values identical to the stored blocks
- **THEN** the schedule status is left unchanged

### Requirement: Only an active schedule can become reviewed
The system SHALL flip a schedule to `reviewed` only from `active`, using a conditional database update; a `draft` schedule MUST NOT become reviewed and a reviewed one stays reviewed.
Enforced: backend/schedules/models.py::Schedule.mark_reviewed_if_active

#### Scenario: Active day reviewed
- **WHEN** `mark_reviewed_if_active` runs on an active schedule
- **THEN** the status becomes `reviewed` and it returns true

Tests: backend/tests/test_status_flow.py::TestMarkReviewedIfActive::test_flips_active_to_reviewed

#### Scenario: Draft or already reviewed
- **WHEN** it runs on a draft or reviewed schedule
- **THEN** the status is unchanged and it returns false

Tests: backend/tests/test_status_flow.py::TestMarkReviewedIfActive::test_refuses_on_draft, backend/tests/test_status_flow.py::TestMarkReviewedIfActive::test_no_op_when_reviewed

### Requirement: Create a manual block
The system SHALL create a block via `POST /api/schedules/{date}/blocks/` from string `start_time`/`end_time`, a trimmed title of 1-255 characters and an optional category (default: the catalog's new-block default), returning 201 with the block fields. A missing schedule for that date is created.
Enforced: backend/schedules/api.py::create_block, backend/schedules/api.py::_create_block

#### Scenario: Valid block
- **WHEN** a user posts a valid title, times and category for a date
- **THEN** the response is 201 with the serialized block and the block is stored on that user's schedule

Tests: backend/tests/test_views.py::TestCreateBlock::test_creates_block, backend/tests/test_views.py::TestCreateBlock::test_title_at_max_length_accepted

#### Scenario: Omitted category
- **WHEN** the body has no `category`
- **THEN** the block uses the user's new-block default category

Tests: backend/tests/test_categories.py::TestPerRequestDefaults::test_create_block_omitted_category_uses_default

#### Scenario: Bad title, times or field types
- **WHEN** the title is empty after trimming or longer than 255 characters, `start_time` or `end_time` is missing, or title, category, start or end is not a string
- **THEN** the response is 400 with the error under that field and nothing is created

Tests: backend/tests/test_views.py::TestCreateBlock::test_title_over_max_length_rejected, backend/tests/test_views.py::TestCreateBlock::test_non_string_title_returns_400_not_500, backend/tests/test_views.py::TestCreateBlock::test_non_string_category_returns_400_not_500, backend/tests/test_views.py::TestCreateBlock::test_non_string_start_time_returns_400, backend/tests/test_views.py::TestCreateBlock::test_non_string_end_time_returns_400, backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_empty_title_rejected, backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_missing_times_rejected

#### Scenario: Invalid URL date
- **WHEN** the `{date}` path segment is not `YYYY-MM-DD`
- **THEN** the response is 400 with `errors.date`

Tests: backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_invalid_date_rejected

### Requirement: Create a block from an imported event
The system SHALL accept `POST /api/schedules/{date}/blocks/from-event/` with the same body rules as manual create, except that boundaries need not lie on the five-minute grid, an omitted category uses the sink category, and the block's stored origin is `calendar`. Re-adding the same event is allowed.
Enforced: backend/schedules/api.py::create_block_from_event, backend/schedules/api.py::_create_block

#### Scenario: Off-grid event times
- **WHEN** an event block is posted with times like `09:07`-`09:52`
- **THEN** it is created with those exact times

Tests: backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_off_grid_times_accepted

#### Scenario: Default category and missing day
- **WHEN** no category is sent and the date has no schedule yet
- **THEN** the block gets category `other` and the schedule is created

Tests: backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_category_defaults_to_other, backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_creates_schedule_when_missing

#### Scenario: Server-owned origin
- **WHEN** a block is created via from-event or manual create, even with a client-supplied `origin` field
- **THEN** the from-event block is stored with origin `calendar` and the manual block with origin `manual`

Tests: backend/tests/test_ai_calendar_privacy.py::test_client_origin_field_cannot_reclassify_import_or_manual_create

#### Scenario: Same event added twice
- **WHEN** the same event is re-added to a free slot
- **THEN** a second block is created

Tests: backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_readd_same_event_allowed

### Requirement: Block category must belong to the user
The system SHALL reject a create or PATCH whose `category` is not a slug in the user's current catalog with 400 `errors.category`, re-checking the catalog when the write is applied.
Enforced: backend/schedules/api.py::_create_block, backend/schedules/api.py::block_detail

#### Scenario: Unknown or non-string slug
- **WHEN** a create or PATCH names a category the user does not have, or sends a non-string category
- **THEN** the response is 400 with `errors.category` and nothing changes

Tests: backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_invalid_category_rejected, backend/tests/test_views.py::TestBlockDetail::test_patch_invalid_category_rejected, backend/tests/test_views.py::TestBlockDetail::test_non_string_category_returns_400_not_500

#### Scenario: Category deleted before the write applies
- **WHEN** the chosen category is deleted after request parsing but before the write is applied
- **THEN** the response is 400, not 500

Tests: backend/tests/test_categories.py::TestPerRequestDefaults::test_create_block_in_txn_deleted_slug_returns_400_not_500

### Requirement: Block times parse as hours and minutes with start before end
The system SHALL parse block times with the `%H:%M` pattern and reject values it cannot parse with 400 `Invalid time format. Use HH:MM.`; every block interval MUST have start before end, so a block cannot span midnight.
Enforced: backend/schedules/time_validation.py::parse_time_field, backend/schedules/time_validation.py::validate_time_range, backend/schedules/planning.py::validate_block_interval

#### Scenario: Unparseable time
- **WHEN** a create, PATCH or reorder sends a time the pattern cannot parse, such as `abc` or `25:00`
- **THEN** the response is 400 with the error under that time field

Tests: backend/tests/test_views.py::TestCreateBlock::test_invalid_time_returns_400, backend/tests/test_views.py::TestBlockDetail::test_update_malformed_time_returns_400, backend/tests/test_reorder.py::TestReorderBlocks::test_invalid_time_format_rejected

#### Scenario: Unpadded time
- **WHEN** a time is sent without zero padding, such as `9:5`
- **THEN** it is parsed as `09:05`

Tests: backend/tests/test_time_validation.py::test_parse_time_preserves_existing_unpadded_format

#### Scenario: Reversed or midnight-spanning interval
- **WHEN** a block is submitted as `23:00`-`01:00` or with start equal to or after end
- **THEN** the response is 400 with `errors.time`

Tests: backend/tests/test_views.py::TestCreateBlock::test_spans_midnight_rejected, backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_start_not_before_end_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_start_not_before_end_rejected

### Requirement: Changed manual boundaries use the five-minute grid
The system SHALL require every boundary that a manual create, PATCH or reorder sets or changes to have minutes divisible by 5 and zero seconds. Boundaries the write leaves unchanged MUST NOT be re-checked, so off-grid imported times survive edits.
Enforced: backend/schedules/planning.py::validate_block_interval, backend/schedules/time_validation.py::validate_five_minute_granularity

#### Scenario: Off-grid manual time
- **WHEN** a manual create sends `09:07`, or a PATCH or reorder changes a boundary to an off-grid minute
- **THEN** the response is 400 and nothing changes

Tests: backend/tests/test_views.py::TestCreateBlock::test_create_block_non_five_minute_time_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_non_five_minute_time_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_changed_time_still_enforces_granularity, backend/tests/test_from_event.py::TestOffGridBlockLifecycle::test_manual_time_edit_still_enforces_granularity, backend/tests/test_from_event.py::TestOffGridBlockLifecycle::test_changing_one_time_to_off_grid_still_rejected

#### Scenario: Unchanged off-grid boundary
- **WHEN** an imported `09:07`-`09:52` block gets a title edit, completion toggle, end-only PATCH, or a reorder that resubmits its times
- **THEN** the write succeeds and the unchanged off-grid boundary is kept

Tests: backend/tests/test_from_event.py::TestOffGridBlockLifecycle::test_completion_toggle_succeeds, backend/tests/test_from_event.py::TestOffGridBlockLifecycle::test_title_edit_succeeds, backend/tests/test_from_event.py::TestOffGridBlockLifecycle::test_partial_end_patch_keeps_off_grid_start, backend/tests/test_from_event.py::TestOffGridBlockLifecycle::test_resubmitting_unchanged_off_grid_times_succeeds, backend/tests/test_reorder.py::TestReorderBlocks::test_unchanged_off_grid_times_accepted

### Requirement: Blocks in a schedule must not overlap
The system SHALL validate the complete final set of blocks after a write as half-open `[start, end)` intervals and reject any overlapping pair with 400 `errors.time`. Touching blocks (one ends when the next starts) are allowed.
Enforced: backend/schedules/planning.py::validate_final_state, backend/schedules/time_validation.py::times_overlap, backend/schedules/api.py::_plan_error_response

#### Scenario: Adjacent blocks
- **WHEN** a block `09:00`-`10:00` is created next to an existing `08:00`-`09:00`
- **THEN** it is accepted

Tests: backend/tests/test_views.py::TestCreateBlock::test_adjacent_blocks_allowed, backend/tests/test_time_validation.py::test_overlap_uses_half_open_intervals, backend/tests/test_schedule_planning.py::test_half_open_adjacency_and_overlap_provenance

#### Scenario: Overlapping create or reorder
- **WHEN** a create or reorder would make two blocks overlap
- **THEN** the response is 400 with `errors.time` (`This block overlaps with an existing block.` or `Reorder would cause overlapping blocks.`) and nothing changes

Tests: backend/tests/test_views.py::TestCreateBlock::test_overlapping_block_returns_400, backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_overlap_rejected_with_manual_create_error, backend/tests/test_reorder.py::TestReorderBlocks::test_overlap_with_unchanged_block_rejected

#### Scenario: Swap in one batch
- **WHEN** a reorder exchanges the times of two adjacent blocks in one request
- **THEN** it succeeds because only the final state is checked

Tests: backend/tests/test_schedule_planning.py::test_final_state_allows_swap_and_batch_shift, backend/tests/test_manual_command_contract.py::test_reorder_accepts_atomic_swap, backend/tests/test_schedule_source_contract.py::test_manual_and_ai_swap_validate_final_state

### Requirement: Manual and imported writes are clamped to the day window
The system SHALL clamp a changed boundary of a manual or from-event create, PATCH or reorder to the user's day window. If the interval is fully outside, or collapses after clamping, it SHALL return 422 `{skipped: true, code: "outside_window", window: {start, end}, errors: {time}}` and write nothing.
Enforced: backend/schedules/planning.py::validate_block_interval, backend/schedules/window.py::clamp_boundary, backend/schedules/api.py::_outside_window_response

#### Scenario: Fully outside
- **WHEN** a create or from-event create targets a span wholly outside the user's window, or a PATCH moves a start past `day_end`
- **THEN** the response is 422 with the skip envelope echoing the user's window bounds and nothing is written

Tests: backend/tests/test_schedule_window_enforcement.py::TestCreateBlockWindow::test_fully_outside_returns_skip_contract_and_creates_nothing, backend/tests/test_schedule_window_enforcement.py::TestCreateBlockWindow::test_custom_window_skip_envelope_echoes_custom_bounds, backend/tests/test_schedule_window_enforcement.py::TestCreateBlockFromEventWindow::test_fully_outside_skipped, backend/tests/test_schedule_window_enforcement.py::TestPatchBlockWindow::test_changed_boundary_jumping_past_far_edge_skipped

#### Scenario: Partially outside
- **WHEN** a written interval crosses `day_start` or `day_end` with the crossing boundary changed
- **THEN** that boundary is stored at the window edge

Tests: backend/tests/test_schedule_window_enforcement.py::TestCreateBlockWindow::test_partially_outside_clamps_to_boundary, backend/tests/test_schedule_window_enforcement.py::TestCreateBlockWindow::test_partially_outside_late_end_clamps_to_day_end, backend/tests/test_schedule_window_enforcement.py::TestCreateBlockFromEventWindow::test_partially_outside_clamps_start_to_day_start, backend/tests/test_schedule_window_enforcement.py::TestPatchBlockWindow::test_changed_start_partially_outside_clamps_to_day_start, backend/tests/test_schedule_window_enforcement.py::TestReorderWindow::test_partial_row_clamps_when_inside_batch_all_legal

#### Scenario: Outside row in a reorder batch
- **WHEN** one reorder row is fully outside the window
- **THEN** the whole batch is rejected with 422 and no row changes

Tests: backend/tests/test_schedule_window_enforcement.py::TestReorderWindow::test_outside_row_aborts_whole_batch

#### Scenario: Window uses the requesting user
- **WHEN** two users have different windows
- **THEN** each write is checked against its own user's window

Tests: backend/tests/test_schedule_window_enforcement.py::TestCreateBlockWindow::test_multi_user_isolation_on_skip_path

### Requirement: Unchanged boundaries are exempt from the window
The system SHALL check only boundaries a write changes against the day window. A block outside a later-narrowed window MUST stay editable for metadata, and a one-boundary edit MUST keep the other stored boundary.
Enforced: backend/schedules/planning.py::validate_block_interval

#### Scenario: Metadata edit outside a narrowed window
- **WHEN** a block sits outside the current window and only its title, category or completion is patched
- **THEN** the write succeeds and its stored times are unchanged

Tests: backend/tests/test_schedule_window_enforcement.py::TestPatchBlockWindow::test_metadata_only_patch_does_not_revalidate_stored_times, backend/tests/test_schedule_planning.py::test_narrowed_window_and_changed_edge_clamp_precede_interval, backend/tests/test_schedule_source_contract.py::test_manual_and_ai_preserve_inherited_off_grid_outside_narrowed_window

#### Scenario: One changed boundary
- **WHEN** a stored `05:00`-`07:00` block under an `08:00`-`23:00` window gets a PATCH setting only `end_time` to `08:00`
- **THEN** the block becomes `05:00`-`08:00`; the inherited start is not moved into the window

Tests: backend/tests/test_schedule_window_enforcement.py::TestPatchBlockWindow::test_changed_boundary_clamps_unchanged_inherited_boundary_preserved

### Requirement: Interval rules depend on the write source
The system SHALL apply interval policy by source: manual and AI writes require the grid and clamp; import skips the grid and clamps; draft requires the grid and rejects out-of-window times without clamping; undo restore skips both grid and window. Sort order above 10000 is allowed only for AI and draft.
Enforced: backend/schedules/planning.py::plan_commands, backend/schedules/planning.py::validate_candidate_fields

#### Scenario: Import versus manual
- **WHEN** an off-grid block partly before the window is planned under the import and manual policies
- **THEN** import clamps it to the window and manual rejects it with code `granularity`

Tests: backend/tests/test_schedule_planning.py::test_source_policies_grid_window_and_unchanged_imported_edge

#### Scenario: Draft and undo
- **WHEN** a draft block ends after the window, and an undo restore contains an off-grid block outside the window
- **THEN** the draft is rejected with `out_of_window` and the restore keeps the exact times

Tests: backend/tests/test_schedule_planning.py::test_draft_rejects_window_and_undo_restores_off_grid_outside_window, backend/tests/test_time_validation.py::test_block_time_validation_can_restore_off_grid_values

#### Scenario: Sort order limit
- **WHEN** a block with `sort_order` 10001 is planned
- **THEN** the manual policy rejects it with code `sort_order` and the AI policy accepts it

Tests: backend/tests/test_schedule_planning.py::test_sort_order_limit_is_source_policy

### Requirement: Edit a block
The system SHALL apply `PATCH /api/blocks/{id}/` to any subset of `title` (trimmed, 1-255), `start_time`, `end_time`, `category`, `is_completed` (boolean) and `sort_order` (plain integer 0-10000), returning 200 with the block. Invalid values MUST return 400 without changes.
Enforced: backend/schedules/api.py::block_detail, backend/schedules/http.py::validate_sort_order

#### Scenario: Title and completion
- **WHEN** a user patches a new title or toggles `is_completed`
- **THEN** the response is 200 with the updated block

Tests: backend/tests/test_views.py::TestBlockDetail::test_update_title, backend/tests/test_views.py::TestBlockDetail::test_toggle_completed

#### Scenario: Sort order
- **WHEN** `sort_order` is a non-integer or outside 0-10000
- **THEN** the response is 400 with `errors.sort_order`; a valid value is stored

Tests: backend/tests/test_views.py::TestBlockDetail::test_patch_sort_order_non_integer_rejected, backend/tests/test_views.py::TestBlockDetail::test_patch_sort_order_out_of_bounds_rejected, backend/tests/test_views.py::TestBlockDetail::test_patch_sort_order_valid

#### Scenario: Invalid title or completion value
- **WHEN** a PATCH sends an empty or over-long title, or a non-boolean `is_completed`
- **THEN** the response is 400 under that field and the block is unchanged

#### Scenario: Non-time edit keeps current times
- **WHEN** a title-only PATCH is applied after another writer moved the block
- **THEN** the other writer's times are kept

Tests: backend/tests/test_views.py::TestBlockDetail::test_non_time_patch_preserves_concurrent_time_update

### Requirement: Delete a block
The system SHALL delete a user's block on `DELETE /api/blocks/{id}/` and return 200 with `ok: true`.
Enforced: backend/schedules/api.py::block_detail

#### Scenario: Owned block
- **WHEN** the owner deletes a block
- **THEN** the response is 200 with `ok: true` and the block no longer exists

Tests: backend/tests/test_views.py::TestBlockDetail::test_delete_block, backend/tests/test_from_event.py::TestOffGridBlockLifecycle::test_delete_succeeds

### Requirement: Reorder or move several blocks atomically
The system SHALL accept `POST /api/blocks/reorder/` with a nonempty `updates` list of at most 100 objects, each with a distinct plain-integer `id`, `start_time`, `end_time` and `sort_order`, all on one schedule owned by the user. It applies all rows or none.
Enforced: backend/schedules/api.py::reorder_blocks, backend/schedules/api.py::MAX_REORDER_UPDATES

#### Scenario: Valid batch
- **WHEN** a user submits new times and orders for blocks of one schedule
- **THEN** the response is 200 and every row has the new values

Tests: backend/tests/test_reorder.py::TestReorderBlocks::test_reorder_success

#### Scenario: Malformed batch
- **WHEN** `updates` is empty or not a list, an entry is not an object, an id is missing, non-integer or duplicated, or `sort_order` is invalid
- **THEN** the response is 400 and nothing changes

Tests: backend/tests/test_reorder.py::TestReorderBlocks::test_empty_updates_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_non_dict_entry_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_missing_id_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_non_integer_id_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_duplicate_ids_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_invalid_sort_order_rejected, backend/tests/test_reorder.py::TestReorderBlocks::test_sort_order_out_of_range_rejected

#### Scenario: Blocks from two schedules
- **WHEN** the ids belong to two different days of the same user
- **THEN** the response is 400 `All blocks must belong to the same schedule.`

Tests: backend/tests/test_reorder.py::TestReorderBlocks::test_cross_schedule_rejected

#### Scenario: One invalid row
- **WHEN** any row of the batch fails validation
- **THEN** no row of the batch is changed

Tests: backend/tests/test_reorder.py::TestReorderBlocks::test_atomicity_no_partial_updates

#### Scenario: Oversized or incomplete batch
- **WHEN** `updates` has 101 entries, or an entry lacks `start_time`, `end_time` or `sort_order`
- **THEN** the response is 400 (`Cannot update more than 100 blocks at once.` or `{field} is required for block {id}.`)

### Requirement: Blocks are scoped to their owner
The system SHALL treat a block that belongs to another user exactly like a missing block: PATCH, DELETE and reorder return 404 and change nothing. All block endpoints MUST require login.
Enforced: backend/schedules/api.py::block_detail, backend/schedules/api.py::reorder_blocks

#### Scenario: Foreign block
- **WHEN** a user patches, deletes or reorders another user's block id
- **THEN** the response is 404 and the block is unchanged

Tests: backend/tests/test_views.py::TestBlockDetail::test_cannot_patch_other_users_block, backend/tests/test_views.py::TestBlockDetail::test_cannot_delete_other_users_block, backend/tests/test_reorder.py::TestReorderBlocks::test_cross_user_returns_404, backend/tests/test_reorder.py::TestReorderBlocks::test_other_users_block_alone_returns_404, backend/tests/test_reorder.py::TestReorderBlocks::test_own_plus_foreign_matches_own_plus_missing_404

#### Scenario: Missing block
- **WHEN** the id does not exist
- **THEN** the response is 404

Tests: backend/tests/test_views.py::TestBlockDetail::test_delete_nonexistent_returns_404, backend/tests/test_reorder.py::TestReorderBlocks::test_nonexistent_block_returns_404

#### Scenario: Anonymous request
- **WHEN** an unauthenticated client calls a block endpoint
- **THEN** it is redirected to login

Tests: backend/tests/test_views.py::TestCreateBlock::test_unauthenticated_returns_302, backend/tests/test_reorder.py::TestReorderBlocks::test_unauthenticated_redirects, backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_unauthenticated_redirects

### Requirement: Block request bodies are JSON objects
The system SHALL reject a block create, PATCH or reorder body that is not valid JSON or not a JSON object with 400, and a body over the shared size limit with 413, before any change.
Enforced: backend/schedules/api.py::_create_block, backend/schedules/api.py::block_detail, backend/schedules/api.py::reorder_blocks

#### Scenario: Non-object or oversized body
- **WHEN** the body is a JSON array, malformed JSON, or larger than the limit
- **THEN** the response is 400 or 413 and no block changes

Tests: backend/tests/test_views.py::TestCreateBlock::test_non_object_body_returns_400, backend/tests/test_views.py::TestCreateBlock::test_oversized_body_returns_413, backend/tests/test_views.py::TestBlockDetail::test_patch_non_object_json_rejected_without_mutation, backend/tests/test_views.py::TestBlockDetail::test_patch_oversized_body_rejected_without_mutation, backend/tests/test_reorder.py::TestReorderBlocks::test_non_object_body_rejected, backend/tests/test_from_event.py::TestCreateBlockFromEvent::test_invalid_json_rejected

### Requirement: Stored blocks always have start before end
The system MUST keep `start_time < end_time` for every stored block through a database check constraint, including writes that bypass application validation. Model validation SHALL also reject a reversed or empty interval and off-grid times.
Enforced: backend/schedules/models.py::TimeBlock.Meta.constraints, backend/schedules/models.py::TimeBlock.clean, backend/schedules/validators.py::validate_five_minute_granularity

#### Scenario: Bulk or queryset write
- **WHEN** a bulk create or queryset update stores start after end
- **THEN** the database rejects it

Tests: backend/tests/test_timeblock_constraint.py::test_database_rejects_invalid_interval_on_bulk_create, backend/tests/test_timeblock_constraint.py::test_database_rejects_invalid_queryset_update_and_preserves_off_grid

#### Scenario: Model validation
- **WHEN** `full_clean` runs on a block with start equal to or after end, or with `09:07`
- **THEN** a validation error is raised

Tests: backend/tests/test_models.py::TestTimeBlock::test_start_before_end, backend/tests/test_models.py::TestTimeBlock::test_start_equals_end, backend/tests/test_models.py::TestTimeBlock::test_five_minute_granularity_invalid

### Requirement: Block wire format and order
The system SHALL serialize a block as `{id, title, start_time, end_time, category, is_completed, sort_order, restore_proof}` with `HH:MM` times, identically in API and page responses, and order a day's blocks by start time then sort order.
Enforced: backend/schedules/serialization.py::serialize_block, backend/schedules/models.py::TimeBlock.Meta.ordering

#### Scenario: Same payload everywhere
- **WHEN** a block is returned by the API, the schedule page and the analytics page
- **THEN** the payloads are identical

Tests: backend/tests/test_block_serialization.py::test_api_block_payload_matches_schedule_and_analytics_pages

#### Scenario: Default ordering
- **WHEN** a schedule's blocks are read
- **THEN** the earlier block comes first

Tests: backend/tests/test_models.py::TestTimeBlock::test_ordering

### Requirement: Deleting a schedule deletes its blocks
The system SHALL delete all of a schedule's blocks when the schedule is deleted.
Enforced: backend/schedules/models.py::TimeBlock.schedule

#### Scenario: Cascade
- **WHEN** a schedule with blocks is deleted
- **THEN** no blocks remain for it

Tests: backend/tests/test_models.py::TestTimeBlock::test_cascade_delete

### Requirement: Admin is inspection-only for days and blocks
The system SHALL let staff view schedules, blocks and schedule settings in Django admin, with a block count per schedule, and MUST refuse admin add, change and delete for them.
Enforced: backend/schedules/admin.py::ScheduleInspectionOnly, backend/schedules/admin.py::ScheduleAdmin

#### Scenario: Admin permissions
- **WHEN** an admin opens the schedule, block or settings admin
- **THEN** viewing is allowed and add, change and delete are not

Tests: backend/tests/test_admin.py::TestScheduleAdmin::test_day_and_policy_admin_surfaces_are_inspection_only, backend/tests/test_admin.py::TestScheduleAdmin::test_inspection_page_renders_without_allowing_writes

#### Scenario: Block count column
- **WHEN** a schedule with two blocks is listed
- **THEN** its block count is 2

Tests: backend/tests/test_admin.py::TestScheduleAdmin::test_block_count_annotation
