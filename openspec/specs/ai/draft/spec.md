# ai/draft Specification

## Purpose
`POST /api/ai/schedules/<date>/generate-draft/` fills an empty day with blocks proposed by the LLM. The prompt is built from the user's template for the day's slot type, recent non-draft history and active rules. The endpoint checks preconditions before spending rate-limit budget, validates the model output as add-only actions, and applies the result atomically through the shared schedule mutation executor. A test-only prompt capture hook is fenced by a startup check.

## Requirements

### Requirement: Draft request validation
The system SHALL require an authenticated POST with a `YYYY-MM-DD` path date, a body within the shared size cap that decodes as a JSON object, and a valid `expected_revision` matching the day's current revision. Each failure is rejected before any provider call or audit row.
Enforced: backend/ai/views.py::ai_generate_draft, backend/ai/views.py::_load_ai_context_sync

#### Scenario: Anonymous request
- **WHEN** an unauthenticated client posts to the draft endpoint
- **THEN** the response is a 302 redirect to login

Tests: backend/tests/test_ai_views_draft.py::TestRouting::test_requires_auth

#### Scenario: Invalid path date
- **WHEN** the path date is not ISO `YYYY-MM-DD`
- **THEN** the response is 400 with an `errors.date` message

Tests: backend/tests/test_ai_views_draft.py::TestRouting::test_invalid_date

#### Scenario: Body is not valid UTF-8 JSON
- **WHEN** the request body cannot be decoded as a JSON object
- **THEN** the response is 400, the provider is not called and no audit row is written

Tests: backend/tests/test_ai_views_draft.py::TestDraftStoredTimezone::test_invalidly_encoded_draft_body_is_rejected

#### Scenario: Missing or invalid expected revision
- **WHEN** `expected_revision` is absent, not a non-negative integer, or differs from the stored revision
- **THEN** the response is 409 with `code` `schedule_changed`, and no blocks or audit rows are created

Tests: backend/tests/test_ai_revision.py::test_ai_and_active_review_require_valid_revision

### Requirement: Draft preconditions run before rate limiting
The system MUST reject a draft with 409 when the day already has blocks and with 422 when the user has no template for the day's slot type (weekday or weekend). These checks, and all request validation failures, MUST NOT call the provider or consume the draft rate-limit budget.
Enforced: backend/ai/views.py::ai_generate_draft

#### Scenario: Day already has blocks
- **WHEN** the target day has at least one block
- **THEN** the response is 409 with a detail asking to delete them before regenerating, the provider is not called and no audit row is written

Tests: backend/tests/test_ai_views_draft.py::TestPreconditions::test_409_when_schedule_has_blocks, backend/tests/test_ai_views_draft.py::TestRateLimitDoesNotFireOnPreconditionFailure::test_409_existing_blocks_does_not_increment

#### Scenario: No template for the slot type
- **WHEN** the user has no template whose type matches the day's slot type
- **THEN** the response is 422 with a detail pointing to Settings and the draft counter is unchanged

Tests: backend/tests/test_ai_views_draft.py::TestPreconditions::test_422_when_no_template, backend/tests/test_ai_views_draft.py::TestRateLimitDoesNotFireOnPreconditionFailure::test_422_no_template_does_not_increment

#### Scenario: Another user's template
- **WHEN** only a different user has a template for the slot type
- **THEN** the lookup does not match and the response is 422

Tests: backend/tests/test_ai_views_draft.py::TestPreconditions::test_cross_user_template_does_not_satisfy_lookup

#### Scenario: Bad date or oversized body
- **WHEN** the date is invalid or the body exceeds the size cap
- **THEN** the request is rejected and the draft counter is unchanged

Tests: backend/tests/test_ai_views_draft.py::TestRateLimitDoesNotFireOnPreconditionFailure::test_invalid_date_does_not_increment, backend/tests/test_ai_views_draft.py::TestRateLimitDoesNotFireOnPreconditionFailure::test_oversized_body_does_not_increment

### Requirement: Draft rate limit bucket
The system SHALL consume one token from the per-user `ai_draft_rl` fixed-window counter, capped by `LLM_DRAFT_RATE_LIMIT_PER_HOUR` (default 10), after preconditions pass and before the provider call. The draft bucket is independent of the chat bucket. Requests that reach the provider, including failed ones, consume budget.
Enforced: backend/ai/views.py::ai_generate_draft, backend/ai/views.py::_consume_rate_limit

#### Scenario: Budget exhausted
- **WHEN** the user's draft counter is already at the hourly limit
- **THEN** the response is 429 with the standard rate-limit detail and `Retry-After: 3600`, the provider is not called and no audit row is written

Tests: backend/tests/test_ai_views_draft.py::test_draft_rate_limit_response_includes_retry_after

#### Scenario: Successful draft counts only against the draft bucket
- **WHEN** a draft succeeds
- **THEN** `ai_draft_rl:<user_id>` is 1 and the chat counter is untouched

Tests: backend/tests/test_ai_views_draft.py::TestHappyPath::test_draft_bucket_independent_of_chat_bucket

#### Scenario: Provider failure still counts
- **WHEN** the draft reaches the service and fails with an AI error such as 503
- **THEN** the draft counter has been incremented

Tests: backend/tests/test_ai_views_draft.py::TestRateLimitDoesNotFireOnPreconditionFailure::test_provider_failure_does_increment

### Requirement: Draft history window
The system SHALL pass as history the user's schedules dated from `LLM_HISTORY_DAYS` (default 7) days before the target date up to but excluding it, with status `active` or `reviewed` only, ordered by date. It MUST load each schedule's daily review and blocks eagerly so prompt building issues no per-day review query.
Enforced: backend/ai/views.py::ai_generate_draft

#### Scenario: Reviews loaded in one query
- **WHEN** a draft is generated with several history days that each have a daily review
- **THEN** exactly one daily-review query is issued for the whole history

Tests: backend/tests/test_ai_views_draft_nplus1.py::test_generate_draft_selects_history_reviews_in_one_query, backend/tests/test_ai_views_draft_nplus1.py::test_prompt_builder_proves_daily_review_nplus1_and_eager_load_fix

#### Scenario: Draft-status days excluded
- **WHEN** a day inside the window has status `draft`
- **THEN** it is not part of the history and its blocks do not appear in the prompt

Tests: backend/tests/test_ai_prompts_draft.py::test_build_draft_user_message_full_context

### Requirement: Draft prompt context
The system SHALL build the draft user message from the target date and weekday, the current local time in the user's stored time zone, the matching template's blocks, each history day with blocks and a completion ratio when blocks were planned, and the user's own active rules by priority. It has no user-command section and ignores any client time-zone field.
Enforced: backend/ai/prompts.py::build_draft_user_message, backend/ai/views.py::ai_generate_draft

#### Scenario: Full context rendered
- **WHEN** the template, an active history day and rules exist
- **THEN** the message contains the schedule date and weekday, current local time, template blocks, history blocks and rules in priority order, and no user-command section

Tests: backend/tests/test_ai_prompts_draft.py::test_build_draft_user_message_full_context, backend/tests/test_ai_prompts_draft.py::test_build_draft_user_message_rules_section_matches_shared_formatter

#### Scenario: Current local date differs from target date
- **WHEN** a draft is requested for a day other than today
- **THEN** the current-time line names the current local date, not the schedule date

Tests: backend/tests/test_ai_prompts_draft.py::test_draft_user_message_renders_current_local_date_not_schedule_date

#### Scenario: Stored time zone governs prompt time
- **WHEN** the user's stored time zone is set and the body carries a different client time zone
- **THEN** the prompt's current time uses the stored zone

Tests: backend/tests/test_ai_views_draft.py::TestDraftStoredTimezone::test_draft_prompt_uses_stored_timezone, backend/tests/test_ai_views_draft.py::TestDraftStoredTimezone::test_optional_timezone_body_is_ignored_in_favor_of_stored_zone

#### Scenario: Only the requester's active rules
- **WHEN** inactive rules or other users' rules exist
- **THEN** only the authenticated user's active rules are passed to the service

Tests: backend/tests/test_ai_views_draft.py::TestActiveRulesWiring::test_only_authenticated_users_active_rules_are_passed

#### Scenario: Stale review snapshot
- **WHEN** a history day's stored review no longer matches the day's current revision
- **THEN** the completion ratio is computed live instead of read from the stored review

Tests: backend/tests/test_ai_prompts_draft.py::test_build_draft_user_message_uses_only_current_review_snapshots

### Requirement: Imported block titles stay out of draft prompts
The system MUST render history blocks whose origin is not `manual` with a placeholder title instead of their stored title, keeping their times and category so the model still sees occupied time.
Enforced: backend/ai/prompts.py::_runtime_block_to_dict

#### Scenario: Imported history block
- **WHEN** a history day contains a block imported from an external source
- **THEN** its original title is absent from the draft prompt

Tests: backend/tests/test_ai_calendar_privacy.py::test_imported_title_is_absent_from_draft_history

### Requirement: Draft provider call
The system SHALL refuse with `AIUnavailableError` when `LLM_API_KEY` is empty or whitespace. Otherwise it SHALL call the provider once with `LLM_DRAFT_MODEL` (default `gpt-4o`), the draft system prompt for the user's day window and categories, JSON-object response format, temperature 0 and `LLM_REQUEST_TIMEOUT`.
Enforced: backend/ai/service.py::run_draft

#### Scenario: Draft model used
- **WHEN** `LLM_DRAFT_MODEL` is configured and the key is set
- **THEN** the provider request names that model and starts with the draft system prompt

Tests: backend/tests/test_ai_service_draft.py::test_run_draft_uses_draft_model_and_returns_result

#### Scenario: AI disabled
- **WHEN** `LLM_API_KEY` is empty
- **THEN** `run_draft` raises `AIUnavailableError` without building a client

Tests: backend/tests/test_ai_service_draft.py::test_run_draft_raises_unavailable_without_key

### Requirement: Draft response validation
The system MUST parse the reply as a JSON object with an `actions` array of at most 20 items and a string `explanation` within `LLM_MAX_EXPLANATION_CHARS`. Every action MUST be an `add` with title, category and explicit HH:MM start and end. Category labels are resolved to slugs first; an unresolvable add category falls back to the sink category.
Enforced: backend/ai/service.py::run_draft, backend/ai/schemas.py::validate_draft_response

#### Scenario: Non-add action
- **WHEN** the model returns a `move`, `remove`, `resize` or `update` action
- **THEN** validation fails and `run_draft` raises `AIParseError` carrying the raw reply

Tests: backend/tests/test_ai_service_draft.py::test_run_draft_rejects_non_add, backend/tests/test_ai_schemas_draft.py::test_rejects_move, backend/tests/test_ai_schemas_draft.py::test_rejects_remove_and_resize

#### Scenario: Untimed add
- **WHEN** an add omits `start_time` and `end_time`
- **THEN** the draft is rejected rather than auto-placed

Tests: backend/tests/test_ai_service_draft.py::test_run_draft_rejects_untimed_add, backend/tests/test_ai_prompts_draft.py::test_draft_add_schema_unchanged_requires_explicit_times

#### Scenario: Envelope errors reported first
- **WHEN** `actions` is not an array
- **THEN** only envelope errors are reported, before any per-action check

Tests: backend/tests/test_ai_schemas_draft.py::test_envelope_check_runs_first

#### Scenario: Category label and unknown category
- **WHEN** an add uses a category label instead of a slug, or a category that matches nothing
- **THEN** the label resolves to its slug and the unknown category resolves to the sink slug

Tests: backend/tests/test_ai_service_draft.py::test_run_draft_resolves_category_label_to_slug, backend/tests/test_ai_service_draft.py::test_run_draft_unresolved_category_falls_back_to_sink

### Requirement: Draft AI error responses
The system SHALL write a best-effort `kind=draft` audit row with command `[DRAFT]` and the raw reply (or error text) for every AI error, then respond with the shared error-status mapping. For `AIParseError` the client detail MUST be the fixed generic parse message, never the validation text.
Enforced: backend/ai/views.py::ai_generate_draft, backend/ai/views.py::AI_PARSE_ERROR_DETAIL

#### Scenario: Error mapped and audited
- **WHEN** the service raises unavailable, timeout, provider or parse errors
- **THEN** the response is 503, 504, 502 or 502 respectively and one draft audit row with `success=False` exists

Tests: backend/tests/test_ai_views_draft.py::TestProviderErrors::test_errors_mapped

#### Scenario: Parse error detail hidden
- **WHEN** the service raises `AIParseError` whose message echoes model text
- **THEN** the 502 detail is the generic parse message and the audit row keeps the raw reply

Tests: backend/tests/test_ai_views_draft.py::TestProviderErrors::test_parse_error_returns_generic_detail

### Requirement: Atomic draft apply
The system SHALL apply a validated draft in one locked mutation: re-check revision, emptiness and the prompt-context fingerprint (blocks, rules, window, time zone, categories, template), then plan all adds under the draft policy and persist them together. Any failure rejects the whole draft with no blocks written.
Enforced: backend/ai/views.py::_apply_draft_sync, backend/ai/views.py::_ai_context_fingerprint

#### Scenario: Schedule row locked
- **WHEN** a draft is applied
- **THEN** the parent schedule row is locked for update during apply

Tests: backend/tests/test_ai_views_draft.py::TestApplyLocksScheduleRow::test_locks_schedule_row

#### Scenario: Concurrent block creation
- **WHEN** another request adds a block while the provider call runs
- **THEN** the draft apply is rejected with 409 and no draft blocks are written

Tests: backend/tests/test_ai_revision.py::test_draft_rejects_concurrent_create_with_expected_revision

#### Scenario: Prompt policy changed during provider call
- **WHEN** the template, a rule, the day window, time zone or categories change while the provider call runs
- **THEN** the apply is rejected with 409 `schedule_changed` and the revision is unchanged

Tests: backend/tests/test_ai_revision.py::test_draft_rejects_template_changed_during_provider, backend/tests/test_ai_revision.py::test_ai_rejects_prompt_policy_changes

#### Scenario: Default gap change does not invalidate
- **WHEN** only the user's default block gap preference changes during the provider call
- **THEN** the draft still applies

Tests: backend/tests/test_ai_views_draft.py::test_gap_change_during_draft_does_not_invalidate

#### Scenario: Overlapping draft blocks
- **WHEN** two returned adds overlap
- **THEN** the response is 400 with detail `Blocks would overlap.` and no blocks are written

Tests: backend/tests/test_ai_views_draft.py::TestDraftDayWindow::test_overlapping_draft_is_rejected_without_partial_writes

### Requirement: Draft blocks must fit the day window
The system MUST reject a draft containing a block outside the user's configured day window with 400 and the block's `action_index`. The detail SHALL name the block title, its attempted interval and the window bounds and say the draft was not saved.
Enforced: backend/ai/views.py::_apply_draft_sync

#### Scenario: Block after a narrowed window end
- **WHEN** the window ends at 21:00 and a returned add runs past it
- **THEN** the response is 400 naming 21:00 and no blocks are written

Tests: backend/tests/test_ai_views_draft.py::TestDraftDayWindow::test_draft_add_rejected_under_narrowed_window_names_narrowed_bound, backend/tests/test_ai_views_draft.py::TestDraftDayWindow::test_draft_add_rejected_under_default_window

#### Scenario: Error identifies the block
- **WHEN** an out-of-window block is rejected
- **THEN** the detail includes its title and interval, the schedule revision and status are unchanged, and the draft audit row stays unsuccessful

Tests: backend/tests/test_ai_views_draft.py::TestDraftDayWindow::test_window_error_explains_failed_draft_and_identifies_block

#### Scenario: Planner error without a matching action
- **WHEN** the planner reports a window error whose action index matches no returned action
- **THEN** the planner's own detail is returned unchanged

Tests: backend/tests/test_ai_views_draft.py::TestDraftDayWindow::test_window_error_without_known_command_keeps_planner_detail

#### Scenario: Blocks at the exact window edges
- **WHEN** a block spans exactly from the window start to the window end
- **THEN** the draft applies

Tests: backend/tests/test_ai_views_draft.py::TestDraftDayWindow::test_rejected_draft_can_be_regenerated_at_exact_window_boundaries, backend/tests/test_ai_views_draft.py::TestDraftDayWindow::test_draft_add_accepted_under_widened_window

### Requirement: Successful draft response
The system SHALL return 200 with the post-apply schedule snapshot plus the model `explanation`, mark the draft audit row successful, store titles trimmed and blocks incomplete, and leave the schedule status as `draft`.
Enforced: backend/ai/views.py::ai_generate_draft, backend/ai/views.py::_mark_success

#### Scenario: Draft applied
- **WHEN** the provider returns two valid adds for an empty day
- **THEN** the response carries both blocks and the explanation, the schedule status stays `draft`, and the audit row has `kind=draft` and `success=True`

Tests: backend/tests/test_ai_views_draft.py::TestHappyPath::test_generates_draft_and_keeps_status_draft

#### Scenario: Past-time block
- **WHEN** a draft block lies before the current local time
- **THEN** it is stored with `is_completed` false

Tests: backend/tests/test_ai_views_draft.py::TestHappyPath::test_draft_persists_past_block_incomplete

### Requirement: Draft prompt capture is a dev-only hook
The system SHALL, when `LLM_DRAFT_CAPTURE_PROMPT_PATH` is non-empty, overwrite that file with the draft user message on every draft call using owner-only permissions and refusing to follow a symlink; write errors are logged, not raised. Startup check `ai.E002` MUST error when the path is set while `DEBUG=False`.
Enforced: backend/ai/service.py::run_draft, backend/ai/checks.py::error_draft_capture_in_production

#### Scenario: Capture file permissions
- **WHEN** the capture path is set and a draft runs
- **THEN** the file is created with mode 0600

Tests: backend/tests/test_ai_service_draft.py::test_capture_writes_with_owner_only_perms

#### Scenario: Symlink at capture path
- **WHEN** the capture path is a symlink
- **THEN** nothing is written through it and the draft still proceeds

Tests: backend/tests/test_ai_service_draft.py::test_capture_refuses_to_follow_symlink

#### Scenario: Production startup with capture set
- **WHEN** the capture path is set and `DEBUG=False`
- **THEN** system check `ai.E002` reports an error

Tests: backend/tests/test_checks.py::TestDraftCaptureProductionError::test_errors_when_prod_with_path_set

#### Scenario: Capture unset or debug on
- **WHEN** the path is unset, the setting is undefined, or `DEBUG=True`
- **THEN** `ai.E002` is silent

Tests: backend/tests/test_checks.py::TestDraftCaptureProductionError::test_silent_when_path_unset, backend/tests/test_checks.py::TestDraftCaptureProductionError::test_silent_when_setting_not_defined, backend/tests/test_checks.py::TestDraftCaptureProductionError::test_silent_when_debug_true
