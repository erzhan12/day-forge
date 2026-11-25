## ADDED Requirements

### Requirement: Draft action cap covers a full template
The system SHALL derive `MAX_DRAFT_ACTIONS` as `MAX_TEMPLATE_BLOCKS` plus 10 headroom actions, independent of the chat cap, and state it in the draft system prompt with an instruction to leave out history-derived additions, never template blocks, to stay under it.
Enforced: backend/ai/schemas.py::MAX_DRAFT_ACTIONS, backend/templates_mgr/limits.py::MAX_TEMPLATE_BLOCKS, backend/ai/prompts.py::build_system_prompt_draft

#### Scenario: Derived cap
- **WHEN** the caps are read
- **THEN** `MAX_DRAFT_ACTIONS` equals `MAX_TEMPLATE_BLOCKS` plus the headroom, template validation uses the same constant, and chat stays at 20

Tests: backend/tests/test_ai_draft_action_cap.py::test_draft_cap_derives_from_template_limit

#### Scenario: Cap in the prompt
- **WHEN** the draft system prompt is rendered
- **THEN** it states the cap and forbids dropping a template block to meet it

Tests: backend/tests/test_ai_draft_action_cap.py::test_draft_prompt_states_cap_and_keeps_template_blocks

#### Scenario: Full template
- **WHEN** the template holds `MAX_TEMPLATE_BLOCKS` blocks and the provider returns all of them
- **THEN** the draft returns 200 and every template block is stored

Tests: backend/tests/test_ai_draft_action_cap.py::TestDraftEndpointCap::test_full_template_generates_complete_draft

## MODIFIED Requirements

### Requirement: Draft provider call
The system SHALL refuse with `AIUnavailableError` when `LLM_API_KEY` is empty or whitespace. Otherwise it SHALL call the provider once with `LLM_DRAFT_MODEL` (default `gpt-4o`), the draft system prompt for the user's day window and categories, JSON-object response format, temperature 0 and the draft-only `LLM_DRAFT_REQUEST_TIMEOUT` (default 60 seconds).
Enforced: backend/ai/service.py::run_draft

#### Scenario: Draft model used
- **WHEN** `LLM_DRAFT_MODEL` is configured and the key is set
- **THEN** the provider request names that model and starts with the draft system prompt

Tests: backend/tests/test_ai_service_draft.py::test_run_draft_uses_draft_model_and_returns_result

#### Scenario: AI disabled
- **WHEN** `LLM_API_KEY` is empty
- **THEN** `run_draft` raises `AIUnavailableError` without building a client

Tests: backend/tests/test_ai_service_draft.py::test_run_draft_raises_unavailable_without_key

#### Scenario: Draft timeout
- **WHEN** a draft calls the provider
- **THEN** the request carries `LLM_DRAFT_REQUEST_TIMEOUT`, not the chat `LLM_REQUEST_TIMEOUT`

Tests: backend/tests/test_ai_draft_action_cap.py::test_run_draft_uses_draft_timeout_and_accepts_cap, backend/tests/test_settings_validation.py::test_draft_request_timeout_default_is_sixty

### Requirement: Draft response validation
The system MUST parse the reply as a JSON object with an `actions` array of at most `MAX_DRAFT_ACTIONS` (60) items and a string `explanation` within `LLM_MAX_EXPLANATION_CHARS`. Every action MUST be an `add` with title, category and explicit HH:MM start and end. Category labels are resolved to slugs first; an unresolvable add category falls back to the sink category.
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

#### Scenario: Action count at and over the cap
- **WHEN** the reply has exactly `MAX_DRAFT_ACTIONS` valid adds, or one more
- **THEN** the first is accepted; the second fails validation and the endpoint returns 502 with the generic parse detail and writes no blocks

Tests: backend/tests/test_ai_draft_action_cap.py::test_validator_accepts_draft_at_cap, backend/tests/test_ai_draft_action_cap.py::test_validator_rejects_one_over_cap, backend/tests/test_ai_draft_action_cap.py::test_run_draft_rejects_one_over_cap, backend/tests/test_ai_draft_action_cap.py::TestDraftEndpointCap::test_draft_one_over_cap_returns_502_without_writes

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

#### Scenario: Maximum-size draft
- **WHEN** a draft with `MAX_DRAFT_ACTIONS` adds is applied, or one whose last add overlaps another
- **THEN** all adds persist with a single revision bump, or none persist and the revision is unchanged

Tests: backend/tests/test_ai_draft_action_cap.py::TestDraftEndpointCap::test_draft_at_cap_is_applied_in_one_revision, backend/tests/test_ai_draft_action_cap.py::TestDraftEndpointCap::test_draft_at_cap_with_overlap_writes_nothing
