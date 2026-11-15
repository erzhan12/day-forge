# ai/chat-mutations Specification

## Purpose
Defines how a validated chat reply becomes schedule changes. Model actions are shape-checked and their categories resolved, then deterministic guards can turn the reply into a server-owned question instead of a write. The pure mutation planner applies the accepted subset atomically, with per-action outcomes, automatic placement of untimed adds and server-owned follow-up questions. The request, privacy and audit contract is in `ai/chat`; server-owned pending intents are in `ai/chat-intents`.

## Requirements

### Requirement: Action shape validation
The system SHALL reject a reply with a parse error when any action has a type outside add, move, remove, resize and update, carries an unknown key, lacks a required field, or has a malformed title, `HH:MM` time, integer `task_id` or category. Errors name the model's own action index.
Enforced: backend/ai/schemas.py::validate_action_shape, backend/ai/service.py::run_chat

#### Scenario: Invalid action type or flat update
- **WHEN** an action has an unknown type, or an update puts changed fields at the top level instead of in `changes`
- **THEN** the turn fails with a parse error whose detail numbers the model's original index

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_invalid_action_types_raise_parse_with_original_indices, backend/tests/test_ai_service_chat.py::TestParsing::test_flat_update_from_provider_raises_parse, backend/tests/test_ai_service_chat.py::TestCategoryResolution::test_error_detail_numbers_by_model_index_not_post_normalisation

#### Scenario: Add with a null target
- **WHEN** an add action carries `task_id: null`
- **THEN** the key is removed before validation, while a non-null `task_id` or any other unknown key on an add still fails

Tests: backend/tests/test_ai_service_chat.py::test_add_null_provider_target_is_canonicalized_without_changing_audit, backend/tests/test_ai_service_chat.py::test_add_non_null_provider_target_remains_invalid, backend/tests/test_ai_service_chat.py::test_add_other_unknown_provider_fields_remain_invalid

#### Scenario: Valid actions keep their order
- **WHEN** a reply lists several valid actions
- **THEN** they are returned in the model's order

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_valid_multiple_actions_preserve_order

### Requirement: Untimed adds and duration operands
The system SHALL let a chat add omit both `start_time` and `end_time`, optionally with a positive `duration_minutes` on the 5-minute grid. A resize SHALL use exactly one of boundary times, `duration_minutes` or a non-zero `duration_delta_minutes` on the grid.
Enforced: backend/ai/schemas.py::validate_action_shape

#### Scenario: Untimed add accepted
- **WHEN** a chat add has a title and category and no times, with or without `duration_minutes`
- **THEN** it passes validation

Tests: backend/tests/test_ai_service_chat.py::TestChatUntimedAdd::test_accepts_untimed_add, backend/tests/test_ai_service_chat.py::TestChatUntimedAdd::test_accepts_untimed_add_with_duration_minutes

#### Scenario: One-sided add time
- **WHEN** an add supplies only one of `start_time` and `end_time`
- **THEN** the turn fails with a parse error

Tests: backend/tests/test_ai_service_chat.py::TestChatUntimedAdd::test_one_sided_time_add_raises_parse

#### Scenario: Valid duration resize
- **WHEN** a resize carries only a grid-aligned `duration_minutes`, or only a non-zero grid-aligned `duration_delta_minutes`
- **THEN** it passes validation

Tests: backend/tests/test_ai_service_chat.py::TestChatDurationResize::test_accepts_absolute_duration_resize_action, backend/tests/test_ai_service_chat.py::TestChatDurationResize::test_accepts_relative_duration_resize_action

#### Scenario: Ambiguous or invalid resize
- **WHEN** a resize mixes duration modes with boundaries, or a duration value is zero, negative, off the grid or not an integer
- **THEN** the turn fails with a parse error

Tests: backend/tests/test_ai_service_chat.py::TestChatDurationResize::test_rejects_ambiguous_duration_resize_action, backend/tests/test_ai_service_chat.py::TestChatDurationResize::test_rejects_invalid_duration_scalar

### Requirement: Category resolution before validation
The system SHALL resolve each action's category to a slug before shape validation: exact slug first, then a case-folded match on slug or label, first catalog entry winning. There is no fuzzy or inflection matching.
Enforced: backend/ai/category_resolution.py::resolve_category, backend/ai/category_resolution.py::normalize_action_categories

#### Scenario: Label or case variant
- **WHEN** the model writes a category label or a case variant from the user's catalog
- **THEN** it is rewritten to that slug

Tests: backend/tests/test_ai_category_resolution.py::TestResolveCategory::test_label_case_variants_match, backend/tests/test_ai_category_resolution.py::TestResolveCategory::test_custom_russian_label_matches, backend/tests/test_ai_service_chat.py::TestCategoryResolution::test_label_resolves_against_user_catalog_not_defaults

#### Scenario: Case-fold collision
- **WHEN** two catalog entries match the value only after case folding
- **THEN** the first entry in catalog order wins

Tests: backend/tests/test_ai_category_resolution.py::TestResolveCategory::test_case_fold_collision_first_catalog_entry_wins

#### Scenario: Inflected form
- **WHEN** the value is an inflected form that matches no slug or label exactly
- **THEN** it does not resolve

Tests: backend/tests/test_ai_category_resolution.py::TestResolveCategory::test_inflected_form_does_not_match

### Requirement: Unresolved categories
The system SHALL give an add with a missing, null or unresolved category the sink slug. For an update it SHALL drop only the unresolved category when other changes remain, and drop the whole action when category was its only change on an existing block. Both update cases are recorded for a server ask.
Enforced: backend/ai/category_resolution.py::normalize_action_categories

#### Scenario: Add falls back to the sink
- **WHEN** an add's category is absent, null or unresolved
- **THEN** it uses the sink category and is not recorded as unresolved

Tests: backend/tests/test_ai_category_resolution.py::TestNormalizeAdd::test_unresolved_falls_back_to_sink, backend/tests/test_ai_category_resolution.py::TestNormalizeAdd::test_absent_category_falls_back_to_sink, backend/tests/test_ai_category_resolution.py::TestNormalizeAdd::test_null_category_falls_back_to_sink

#### Scenario: Update with time and unresolved category
- **WHEN** an update changes time and an unresolved category
- **THEN** the time change applies and the response asks which category to use

Tests: backend/tests/test_ai_category_resolution.py::TestNormalizeUpdate::test_unresolved_with_other_changes_drops_category_keeps_action, backend/tests/test_ai_views_chat.py::TestCategoryAsk::test_update_with_time_and_unresolved_category_applies_time_and_asks

#### Scenario: Category-only update
- **WHEN** an otherwise valid update for an existing block changes only an unresolved category
- **THEN** nothing is written and the response is a 200 with the server's category question and "Nothing was changed."

Tests: backend/tests/test_ai_service_chat.py::TestCategoryResolution::test_category_only_unresolved_update_drops_to_empty_actions, backend/tests/test_ai_views_chat.py::TestCategoryAsk::test_category_only_unresolved_returns_ask_without_mutating, backend/tests/test_ai_views_chat.py::TestCategoryAskIndexSpacesEndToEnd::test_single_category_only_update_takes_server_ask_branch

#### Scenario: Category-only update on an unknown block
- **WHEN** the category-only update names a block not on the schedule, or is otherwise malformed
- **THEN** it is not dropped and the turn fails with a parse error

Tests: backend/tests/test_ai_service_chat.py::TestCategoryResolution::test_category_only_unresolved_unknown_task_id_still_raises_parse, backend/tests/test_ai_category_resolution.py::TestNormalizeUpdate::test_guard_kept_untouched_when_task_id_unknown

### Requirement: Server-owned category question
The system SHALL ask about the first unresolved update category by naming the block (masked when protected, truncated when long) and listing the user's category labels in catalog order. The rejected value never appears. A time-resolution ask takes precedence.
Enforced: backend/ai/views.py::_build_category_ask, backend/ai/views.py::_finish_chat_sync

#### Scenario: Question copy
- **WHEN** an unresolved record exists and the catalog is not empty
- **THEN** the ask names the block, or "that block" when unknown, and lists labels in catalog order

Tests: backend/tests/test_ai_views_chat.py::TestBuildCategoryAsk::test_lists_labels_in_catalog_order_and_names_block, backend/tests/test_ai_views_chat.py::TestBuildCategoryAsk::test_unknown_task_id_falls_back_to_that_block, backend/tests/test_ai_views_chat.py::TestBuildCategoryAsk::test_truncates_long_title

#### Scenario: Time question wins
- **WHEN** both a skipped time change and an unresolved category are pending
- **THEN** the response asks about the time

Tests: backend/tests/test_ai_views_chat.py::TestCategoryAsk::test_resolution_ask_outranks_category_ask

### Requirement: Live category check at apply
The system SHALL re-check every add and update category against the user's catalog under the write lock and reject an unknown slug with 400 `errors.action_index` and detail "invalid category", writing nothing.
Enforced: backend/ai/views.py::_apply_actions_sync

#### Scenario: Category no longer exists
- **WHEN** the planned action names a category slug not in the current catalog
- **THEN** the response is 400 and the block keeps its old category

Tests: backend/tests/test_ai_views_chat.py::test_chat_nested_update_revalidates_category_deleted_mid_request

### Requirement: Structural target errors abort the turn
The system SHALL reject the whole turn with 400 `errors.action_index` when a move, resize, update or remove names a block not on this schedule, or a block already removed earlier in the same turn.
Enforced: backend/ai/mutation_planner.py::_normalize_actions, backend/ai/views.py::_apply_actions_sync

#### Scenario: Unknown or foreign block
- **WHEN** an action references a missing block or another user's block
- **THEN** the response is 400 with the "Referenced block no longer exists" detail and nothing is written

Tests: backend/tests/test_ai_mutation_planner.py::TestPlannerEdgeCases::test_plan_unknown_task_id, backend/tests/test_ai_mutation_planner.py::test_plan_update_unknown_task_id, backend/tests/test_ai_views_chat.py::TestSharedApplyCoverage::test_cross_user_task_id_returns_400, backend/tests/test_ai_views_chat.py::test_chat_rejects_nested_update_for_another_users_task

#### Scenario: Action after removal
- **WHEN** a block is removed and a later action in the same turn removes or edits it again
- **THEN** the turn is rejected with a plan error

Tests: backend/tests/test_ai_mutation_planner.py::TestPlannerEdgeCases::test_plan_post_remove_action_is_rejected, backend/tests/test_ai_mutation_planner.py::TestPlannerEdgeCases::test_plan_duplicate_remove_is_rejected

### Requirement: Final-state planning with partial outcomes
The system SHALL plan the final state of all actions together, so swaps and shifts work regardless of action order. A window, grid, interval or overlap failure SHALL skip only that action's time change; independent metadata and other actions still persist in one atomic diff.
Enforced: backend/ai/mutation_planner.py::plan_mutations

#### Scenario: Swap and mass shift
- **WHEN** actions swap two blocks or shift many blocks in any order
- **THEN** the final intervals are applied without overlap errors

Tests: backend/tests/test_ai_mutation_planner.py::TestPlannerEdgeCases::test_plan_two_block_swap, backend/tests/test_ai_mutation_planner.py::TestMassForwardShift::test_plan_mass_forward_shift_order_invariant

#### Scenario: Time conflicts but metadata is valid
- **WHEN** an update changes a title and a time that overlaps an unchanged block
- **THEN** the title applies, the time is skipped with reason `overlap`, and the outcome status is `partial`

Tests: backend/tests/test_ai_mutation_planner.py::test_update_metadata_persists_when_requested_time_conflicts, backend/tests/test_ai_views_chat.py::test_chat_partially_applies_metadata_and_returns_one_resolution_ask

#### Scenario: Off-grid time with valid metadata
- **WHEN** an update changes a title and sets an end time off the 5-minute grid
- **THEN** the title applies, the end is skipped with reason `granularity`, and the outcome status is `partial`

Tests: backend/tests/test_ai_mutation_planner.py::test_off_grid_update_keeps_metadata_and_reports_partial_outcome

#### Scenario: Changed blocks collide with each other
- **WHEN** two changed blocks would overlap each other
- **THEN** both time changes are skipped with reason `unresolved_conflict`

Tests: backend/tests/test_ai_mutation_planner.py::TestPlannerEdgeCases::test_plan_rejects_genuine_final_overlap, backend/tests/test_ai_mutation_planner.py::TestPlannerEdgeCases::test_plan_overlap_attribution_is_deterministic

#### Scenario: Fully skipped turn
- **WHEN** every action is skipped
- **THEN** the response is 200 with `applied: false` and an ask, nothing is persisted and the day status is unchanged

Tests: backend/tests/test_ai_views_chat.py::TestChatBatchMutationExecutor::test_chat_overlap_rolls_back_and_preserves_status

### Requirement: Move and resize time derivation
The system SHALL derive the end of a start-only move or update from the block's current duration rounded up to 5 minutes, and SHALL skip with `out_of_window` a derived end that wraps past midnight. Later same-turn actions on a block build on its earlier result and keep its placement direction.
Enforced: backend/ai/mutation_planner.py::compute_move_resize_times, backend/ai/mutation_planner.py::_normalize_actions

#### Scenario: Move keeps duration
- **WHEN** a move supplies only a new start
- **THEN** the block keeps its duration

Tests: backend/tests/test_ai_views_chat.py::TestSharedApplyCoverage::test_move_preserves_duration, backend/tests/test_ai_mutation_planner.py::test_nested_update_start_only_preserves_effective_duration_and_wrap_provenance

#### Scenario: Move wraps past midnight
- **WHEN** the derived end would pass midnight
- **THEN** the time change is skipped with `out_of_window` and no slot suggestion, and the 200 response asks for another time

Tests: backend/tests/test_ai_mutation_planner.py::TestPlannerEdgeCases::test_plan_effective_midnight_wrap_has_specific_detail, backend/tests/test_ai_views_chat.py::TestSharedApplyCoverage::test_duration_preserving_move_past_midnight_returns_clear_error

#### Scenario: Chained same-block actions
- **WHEN** a later action on the same block supplies a time but no direction
- **THEN** it builds on the earlier effective times and keeps the earlier direction

Tests: backend/tests/test_ai_mutation_planner.py::test_same_task_bare_move_preserves_prior_direction, backend/tests/test_ai_mutation_planner.py::TestPlannerEdgeCases::test_plan_same_target_resize_then_bare_move

### Requirement: Duration resize
The system SHALL compute a duration resize end in whole minutes from the effective start (absolute) or effective end (delta), and SHALL skip rather than clamp it: below 5 minutes as `interval`, outside the window as `out_of_window`, off-grid as `granularity`.
Enforced: backend/ai/mutation_planner.py::plan_mutations

#### Scenario: Resize applied
- **WHEN** a chat resize sets a valid absolute duration
- **THEN** only the block's end changes

Tests: backend/tests/test_ai_views_chat.py::TestChatDurationResize::test_chat_applies_duration_resize_end_to_end, backend/tests/test_ai_mutation_planner.py::TestDurationResize::test_plan_resize_absolute_duration_emits_end_only_update

#### Scenario: Resize past the window
- **WHEN** the derived end passes the user's day end or falls below the floor
- **THEN** the end change is skipped and the stored block is unchanged

Tests: backend/tests/test_ai_views_chat.py::TestChatDurationResize::test_chat_duration_resize_rejected_past_user_day_end, backend/tests/test_ai_mutation_planner.py::TestDurationResize::test_plan_duration_past_window_is_rejected_not_clamped, backend/tests/test_ai_mutation_planner.py::TestDurationResize::test_plan_relative_resize_below_floor_is_skipped

#### Scenario: Failed resize does not feed later moves
- **WHEN** a duration resize is rejected and a later action moves the same block
- **THEN** the move does not inherit the rejected duration

Tests: backend/tests/test_ai_mutation_planner.py::TestDurationResize::test_failed_overlap_duration_does_not_inflate_later_bare_move, backend/tests/test_ai_mutation_planner.py::TestDurationResize::test_unrepresentable_duration_poison_blocks_later_bare_move

### Requirement: Day window enforcement
The system SHALL judge AI time changes against the user's saved day window, skipping with `out_of_window` a change whose interval lies entirely outside it, including a supplied start after the window end or a supplied end before the window start.
Enforced: backend/ai/mutation_planner.py::plan_mutations

#### Scenario: Narrowed and widened windows
- **WHEN** the user's window is narrowed or widened
- **THEN** adds and updates are judged against that window, and other users are unaffected

Tests: backend/tests/test_ai_views_chat.py::TestChatNonDefaultDayWindow::test_add_rejected_under_narrowed_window_names_narrowed_bound, backend/tests/test_ai_views_chat.py::TestChatNonDefaultDayWindow::test_add_accepted_under_widened_window, backend/tests/test_ai_views_chat.py::TestChatNonDefaultDayWindow::test_narrowed_window_does_not_affect_other_user, backend/tests/test_ai_mutation_planner.py::TestNonDefaultDayWindow::test_create_rejected_under_narrowed_window_names_narrowed_bound

#### Scenario: Supplied boundary outside the window
- **WHEN** a supplied start is after the window end, or a supplied end is before the window start
- **THEN** the time change is skipped with `out_of_window`

Tests: backend/tests/test_ai_mutation_planner.py::TestNonDefaultDayWindow::test_supplied_start_past_day_end_is_rejected_symmetric_bound, backend/tests/test_ai_mutation_planner.py::TestNonDefaultDayWindow::test_supplied_end_before_day_start_is_rejected_symmetric_bound

### Requirement: Automatic placement of untimed adds
The system SHALL place each untimed add after the overlap pass, in action order, on the 5-minute grid with a default 25-minute duration and the user's `default_block_gap_minutes` on both sides. Search starts at the window start, or for today at the local time rounded up to the grid.
Enforced: backend/ai/mutation_planner.py::plan_mutations, backend/ai/views.py::_earliest_start

#### Scenario: Placed from the current time today
- **WHEN** an untimed add is planned for today
- **THEN** it never starts before the current local time rounded up to the next grid minute

Tests: backend/tests/test_ai_mutation_planner.py::TestAutoPlacement::test_empty_today_places_at_earliest_start_default_25, backend/tests/test_ai_mutation_planner.py::TestAutoPlacement::test_today_never_starts_before_earliest_start, backend/tests/test_ai_views_chat.py::TestAutoPlacementIntegration::test_untimed_add_uses_fresh_apply_time_local_now

#### Scenario: Another date
- **WHEN** the schedule date is not the user's local today
- **THEN** placement searches from the window start

Tests: backend/tests/test_ai_mutation_planner.py::TestAutoPlacement::test_non_today_searches_from_window_start, backend/tests/test_ai_views_chat.py::TestEarliestStartHelper::test_non_today_date_returns_none

#### Scenario: Gap on both sides
- **WHEN** neighbours exist and the saved gap is set
- **THEN** the new block keeps that gap from each neighbour; explicit-time adds and moves ignore the gap

Tests: backend/tests/test_ai_mutation_planner.py::test_configured_gap_on_both_sides, backend/tests/test_ai_mutation_planner.py::test_explicit_add_and_move_ignore_default_gap, backend/tests/test_ai_views_chat.py::test_chat_captures_gap_and_places_with_it

#### Scenario: No room left
- **WHEN** no slot fits in the remaining window, or the clock is past the window end
- **THEN** the add is skipped with `no_slot` and the response asks for a shorter duration or a specific free time

Tests: backend/tests/test_ai_mutation_planner.py::TestAutoPlacement::test_no_slot_when_window_fully_padded, backend/tests/test_ai_views_chat.py::TestAutoPlacementIntegration::test_untimed_add_no_slot_surfaces_ask, backend/tests/test_ai_views_chat.py::TestEarliestStartHelper::test_after_window_end_returns_sentinel_at_or_past_end

### Requirement: Reduced gap in the first free window
The system SHALL keep a full-gap placement that fits in the first free window. Otherwise it SHALL retry only that window with gaps reduced by 5 minutes down to zero, right-aligned and not before the search floor, and then fall back to the full-gap forward search.
Enforced: backend/ai/mutation_planner.py::_find_auto_slot

#### Scenario: Full gap fits
- **WHEN** the first free window between neighbours fits the block with the full gap
- **THEN** the placement is unchanged by the retry logic

Tests: backend/tests/test_ai_mutation_planner.py::TestAutoPlacementGapPreference::test_full_gap_between_neighbours_is_unchanged

#### Scenario: Tight window before a block
- **WHEN** the first free window is too short for the full gap but fits with a smaller one
- **THEN** the block is placed there with the largest gap that fits

Tests: backend/tests/test_ai_mutation_planner.py::TestAutoPlacementGapPreference::test_tight_window_uses_five_minute_gap_on_both_sides, backend/tests/test_ai_mutation_planner.py::TestAutoPlacementGapPreference::test_issue_260_zero_gap_before_standup

#### Scenario: Zero gap preference
- **WHEN** the saved gap is zero
- **THEN** there are no retry levels and blocks may touch

Tests: backend/tests/test_ai_mutation_planner.py::TestAutoPlacementGapPreference::test_zero_default_gap_has_no_retry_levels_and_keeps_fallback

### Requirement: Directional slot suggestion
The system SHALL compute a slot suggestion only for a time change skipped as `overlap`. The `exact` direction yields a direction-required marker; `later` or `earlier` searches the window on the grid for the nearest free interval of the same length.
Enforced: backend/ai/free_slot.py::find_slot, backend/ai/mutation_planner.py::plan_mutations

#### Scenario: Directional search
- **WHEN** a later or earlier search runs from a desired interval
- **THEN** it returns the nearest grid-aligned free interval inside the window, or nothing when the window is full

Tests: backend/tests/test_free_slot.py::test_finds_nearest_later_slot_on_the_grid, backend/tests/test_free_slot.py::test_fully_packed_window_returns_none, backend/tests/test_free_slot.py::test_directional_monotonicity_both_directions

#### Scenario: Exact direction or invalid duration
- **WHEN** the direction is `exact`, or the duration is not positive on the grid
- **THEN** the result is the direction-required marker or no suggestion respectively

Tests: backend/tests/test_free_slot.py::test_exact_requires_a_direction_and_invalid_duration_has_no_proposal

### Requirement: Server-owned resolution question
The system SHALL ask one server-owned English question when time work is skipped, chosen by fixed precedence: a concrete suggestion, direction required, unresolved conflict, no slot in the attempted direction, `no_slot`, `out_of_window`, a skipped add, then a generic message.
Enforced: backend/ai/views.py::_build_resolution_ask

#### Scenario: Order-independent choice
- **WHEN** several skipped outcomes exist in either order
- **THEN** the same highest-precedence question is chosen

Tests: backend/tests/test_ai_views_chat.py::TestResolutionAskPrecedence::test_unresolved_conflict_wins_over_skipped_add_both_orders, backend/tests/test_ai_views_chat.py::TestResolutionAskPrecedence::test_window_question_precedes_generic_invalid_create_in_either_order, backend/tests/test_ai_views_chat.py::TestResolutionAskNoSlotPrecedence::test_no_slot_wins_over_generic_skipped_add_both_orders

#### Scenario: Window and direction questions
- **WHEN** an exact move falls outside the window, or an exact move conflicts and the user then gives a direction
- **THEN** the first asks for a time within the day, the second offers a concrete free slot

Tests: backend/tests/test_ai_views_chat.py::test_chat_out_of_window_exact_move_yields_window_ask_not_direction, backend/tests/test_ai_views_chat.py::test_chat_exact_conflict_then_direction_yields_concrete_suggestion, backend/tests/test_ai_views_chat.py::test_chat_create_outside_custom_window_asks_for_time_in_day

### Requirement: Persisted diff and day status
The system SHALL persist the planned diff through the shared mutation executor in one transaction, giving AI-created blocks the normal append sort order. A non-empty diff SHALL move a draft or reviewed day to active; a same-value or empty plan keeps status and revision.
Enforced: backend/ai/views.py::_apply_actions_sync, backend/ai/views.py::_persist_mutation_diff

#### Scenario: Status transition
- **WHEN** a reviewed day receives an applied AI change
- **THEN** the day becomes active

Tests: backend/tests/test_ai_views_chat.py::TestSharedApplyCoverage::test_reviewed_schedule_transitions_to_active

#### Scenario: Same-value update
- **WHEN** an AI update sets values equal to the current ones
- **THEN** status and revision are unchanged

Tests: backend/tests/test_ai_views_chat.py::TestSharedApplyCoverage::test_same_value_ai_update_does_not_change_status_or_revision

#### Scenario: Several creates in one turn
- **WHEN** one turn creates several blocks
- **THEN** each receives a distinct append sort order

Tests: backend/tests/test_ai_views_chat.py::TestSharedApplyCoverage::test_multiple_creates_receive_distinct_sort_orders

#### Scenario: Row validation failure
- **WHEN** persisting a planned row fails model validation
- **THEN** the whole diff rolls back and the response is 400 with that action's index

Tests: backend/tests/test_ai_views_chat.py::TestSharedApplyCoverage::test_persist_validation_error_rolls_back_with_action_index

### Requirement: Replay guard
The system SHALL skip the whole turn when an add's title does not trace to the latest user turn but has evidence in earlier handled turns. The 200 response writes nothing, says "Nothing was changed.", asks what to add, and marks every action skipped with `replay_guard`.
Enforced: backend/ai/replay_guard.py::find_replayed_actions, backend/ai/views.py::_replay_guard_response

#### Scenario: Earlier add replayed
- **WHEN** a follow-up turn names a new item and the model re-adds the previous turn's title, possibly with a numeric suffix
- **THEN** no action applies, including sibling non-add actions

Tests: backend/tests/test_ai_views_chat.py::TestReplayGuard::test_issue_219_two_turn_sequence_does_not_replay, backend/tests/test_ai_views_chat.py::TestReplayGuard::test_guard_aborts_whole_turn, backend/tests/test_ai_replay_guard.py::TestSuffixStrippingAndNormalisation::test_numeric_suffix_flagged_as_replay

#### Scenario: Traceable or explicitly repeated title
- **WHEN** the add title shares a significant token, allowing simple inflection, with the latest turn
- **THEN** the add is allowed

Tests: backend/tests/test_ai_views_chat.py::TestReplayGuard::test_explicit_repeat_add_with_rule_suffix_is_allowed, backend/tests/test_ai_views_chat.py::TestReplayGuard::test_rephrased_title_is_allowed, backend/tests/test_ai_replay_guard.py::TestInflectionAllowed::test_russian_case_inflection_allowed

#### Scenario: Only adds are checked
- **WHEN** the reply contains moves, removes, resizes or updates
- **THEN** those actions are never flagged themselves

Tests: backend/tests/test_ai_replay_guard.py::TestScope::test_non_add_actions_never_returned

### Requirement: Replay guard around asks and errors
The system SHALL exclude a contiguous chain of pending ask turns, or of failed turns marked `is_error`, from replay evidence, while blocks already applied in that chain stay evidence. Without `applied_add_block_ids` it SHALL treat same-title existing blocks as applied.
Enforced: backend/ai/replay_guard.py::find_replayed_actions

#### Scenario: Answer to a pending ask
- **WHEN** the previous assistant turn is a real ask and the user answers it
- **THEN** the pending add may apply, but an add from an older handled turn is still flagged

Tests: backend/tests/test_ai_views_chat.py::TestReplayGuard::test_pending_ask_answer_skips_guard, backend/tests/test_ai_replay_guard.py::TestIsAskChecksOlderTurns::test_pending_ask_still_flags_add_from_older_completed_turn, backend/tests/test_ai_views_chat.py::TestReplayGuard::test_pending_ask_does_not_repeat_partially_applied_sibling

#### Scenario: Retry after an error
- **WHEN** the previous assistant turn is marked `is_error` and the user retries
- **THEN** the never-applied add may apply, but an earlier successful add is still flagged

Tests: backend/tests/test_ai_views_chat.py::TestReplayGuard::test_retry_after_error_bubble_is_allowed, backend/tests/test_ai_views_chat.py::TestReplayGuard::test_fresh_turn_after_error_cannot_replay_earlier_add, backend/tests/test_ai_views_chat.py::TestReplayGuard::test_chained_failure_retry_is_allowed

#### Scenario: Markers missing
- **WHEN** a question-shaped assistant turn lacks `is_ask`, or ask turns lack `applied_add_block_ids`
- **THEN** the guard stays enforced and same-title existing blocks count as applied

Tests: backend/tests/test_ai_views_chat.py::TestReplayGuard::test_pending_ask_without_flag_is_enforced, backend/tests/test_ai_replay_guard.py::TestOnlyRealAskDisablesGuard::test_question_shaped_explanation_without_is_ask_still_enforced, backend/tests/test_ai_replay_guard.py::TestIsErrorRetryWidening::test_older_client_failed_answer_fails_closed_for_same_title

### Requirement: Relative add guard
The system SHALL NOT auto-place an add requested before or after an existing block. When the active request has such a relation, the turn SHALL return a server question unless each checked add has explicit times on the correct side of the one resolved anchor, including any stated gap.
Enforced: backend/ai/relative_add_guard.py::relative_add_guard_ask, backend/ai/views.py::_finish_chat_sync

#### Scenario: Untimed or misordered relative add
- **WHEN** the user asks to add X after Y and the model returns an untimed add or a start before Y ends plus the stated gap
- **THEN** nothing is written and the response asks for a start time after Y

Tests: backend/tests/test_ai_relative_add_guard.py::test_untimed_after_existing_block_requires_concrete_time, backend/tests/test_ai_relative_add_guard.py::test_explicit_add_before_anchor_is_rejected, backend/tests/test_ai_relative_add_guard.py::test_explicit_add_must_keep_requested_gap, backend/tests/test_ai_views_chat.py::TestAutoPlacementIntegration::test_relative_untimed_add_asks_instead_of_placing_before_anchor

#### Scenario: Correct explicit placement and independent siblings
- **WHEN** the add starts after the anchor, or a sibling add is not the one named in the relation
- **THEN** the turn applies normally

Tests: backend/tests/test_ai_relative_add_guard.py::test_explicit_add_after_anchor_is_allowed, backend/tests/test_ai_relative_add_guard.py::test_multi_add_checks_relative_target_without_blocking_untimed_sibling, backend/tests/test_ai_views_chat.py::TestAutoPlacementIntegration::test_relative_add_does_not_block_independent_untimed_sibling

#### Scenario: Relation to a clock time
- **WHEN** the relation names a clock time rather than a block
- **THEN** the guard asks nothing

Tests: backend/tests/test_ai_relative_add_guard.py::test_clock_reference_is_not_treated_as_a_block

#### Scenario: Unknown anchor
- **WHEN** the relation names no single existing block and no clock time
- **THEN** the response asks which block; the newest reply naming exactly one block resolves it

Tests: backend/tests/test_ai_relative_add_guard.py::test_unknown_reference_asks_which_block, backend/tests/test_ai_relative_add_guard.py::test_answer_naming_a_block_resolves_unknown_anchor, backend/tests/test_ai_relative_add_guard.py::test_newest_reply_overrides_an_earlier_answer

#### Scenario: Russian request
- **WHEN** the request or the latest reply contains Cyrillic
- **THEN** the question is in Russian

Tests: backend/tests/test_ai_relative_add_guard.py::test_russian_requests_get_russian_questions, backend/tests/test_ai_relative_add_guard.py::test_english_request_with_russian_reply_gets_russian_question

### Requirement: Implicit add rewrite
The system SHALL prefix "add " (or "добавь " for Cyrillic text) to the provider-bound copy of a latest turn that has no command verb, is not a question or short reply, does not answer an ask or follow an error, and is not a time or duration fragment following an assistant reply. Stored transcript, audit and replay checks keep the original text.
Enforced: backend/ai/implicit_add.py::apply_implicit_add, backend/ai/service.py::run_chat

#### Scenario: Bare title
- **WHEN** the latest turn is a bare activity name
- **THEN** the provider receives it prefixed with an add command

Tests: backend/tests/test_ai_implicit_add.py::TestPrefixed::test_bare_title_gets_add_prefix, backend/tests/test_ai_implicit_add.py::TestPrefixed::test_cyrillic_bare_title_gets_dobavi_prefix, backend/tests/test_ai_service_chat.py::TestImplicitAddRewrite::test_bare_title_sent_as_add_to_provider, backend/tests/test_ai_implicit_add.py::test_fresh_title_after_apply_still_gets_add_prefix

#### Scenario: Left unchanged
- **WHEN** the turn has a command verb, is a question or short reply, or follows an ask or error turn
- **THEN** it is sent as typed

Tests: backend/tests/test_ai_implicit_add.py::TestUnchangedExplicitVerb::test_english_verb_present, backend/tests/test_ai_implicit_add.py::TestUnchangedQuestion::test_question_mark, backend/tests/test_ai_implicit_add.py::TestUnchangedShortReply::test_thanks, backend/tests/test_ai_implicit_add.py::TestUnchangedPendingAsk::test_pending_ask_answer_left_alone, backend/tests/test_ai_implicit_add.py::TestUnchangedAfterErrorBubble::test_try_again_after_error_left_alone

#### Scenario: Attribute follow-up after an assistant reply
- **WHEN** the latest turn starts with an `HH:MM` time (optionally after `at` or `в`) or a `for`/`на` duration and the previous turn is an assistant reply
- **THEN** it is sent as typed, even with no pending question

Tests: backend/tests/test_ai_implicit_add.py::test_attribute_follow_up_after_apply_keeps_original_text

### Requirement: Refine the block just added
The system SHALL let an attribute-only follow-up refine an existing block by updating only the requested fields of that block's ID. It MUST NOT add a second copy; a duplicate add is still rejected by the replay guard. An ambiguous target SHALL get a question without changing the schedule.
Enforced: backend/ai/prompts.py::SYSTEM_PROMPT_CHAT, backend/ai/implicit_add.py::apply_implicit_add, backend/ai/replay_guard.py::find_replayed_actions

#### Scenario: Refine without a duplicate
- **WHEN** after adding a block the user sends only a new time, duration or category
- **THEN** the existing block is updated and no new block is created

Tests: backend/tests/test_ai_views_chat.py::test_refine_just_added_block_without_duplicate

#### Scenario: Provider re-adds instead of updating
- **WHEN** the provider answers an attribute follow-up with a duplicate add
- **THEN** the replay guard skips the turn and nothing is written

Tests: backend/tests/test_ai_views_chat.py::test_refinement_does_not_allow_provider_to_add_a_duplicate
