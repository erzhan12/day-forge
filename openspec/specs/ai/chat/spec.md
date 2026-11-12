# ai/chat Specification

## Purpose
`POST /api/ai/schedules/<date>/chat/` is the multi-turn AI command chat. The client sends the whole transcript with a durable request UUID and the expected schedule revision. The server validates it, records a durable claim, captures schedule and policy context under the user lock, calls the LLM outside any transaction, validates the reply envelope and stores one terminal result per request atomically with any schedule change. This spec covers the request, provider, privacy and audit contract. How model actions become schedule changes is in `ai/chat-mutations`.

## Requirements

### Requirement: Transcript validation before side effects
The system SHALL reject a malformed `messages` array with 400 `errors.messages` before creating a Schedule row, a claim or an audit row, and before consuming rate-limit budget.
Enforced: backend/ai/views.py::_validate_chat_messages, backend/ai/views.py::ai_chat

#### Scenario: Anonymous request
- **WHEN** an unauthenticated client posts to the chat endpoint
- **THEN** the request is redirected to login and nothing is written

Tests: backend/tests/test_ai_views_chat.py::TestValidation::test_requires_auth

#### Scenario: Invalid date or body
- **WHEN** the path date is not ISO `YYYY-MM-DD`, the body exceeds the shared size cap, or the body is not a JSON object
- **THEN** the response is 400 `errors.date`, the shared oversized-body error, or a JSON-body 400 respectively

Tests: backend/tests/test_ai_views_chat.py::TestValidation::test_invalid_date, backend/tests/test_ai_views_chat.py::TestValidation::test_oversized_body, backend/tests/test_ai_views_chat.py::TestValidation::test_invalid_json_body, backend/tests/test_ai_views_chat.py::TestValidation::test_non_object_json_root_returns_400

#### Scenario: Shape and role order
- **WHEN** `messages` is missing, not an array, empty, longer than `LLM_CHAT_MAX_TURNS`, does not strictly alternate starting with `user`, or does not end with a `user` turn
- **THEN** the response is 400 with an `errors.messages` string; a transcript of exactly `LLM_CHAT_MAX_TURNS` turns is accepted

Tests: backend/tests/test_ai_views_chat.py::TestValidation::test_messages_missing, backend/tests/test_ai_views_chat.py::TestValidation::test_empty_messages, backend/tests/test_ai_views_chat.py::TestValidation::test_non_alternating_roles, backend/tests/test_ai_views_chat.py::TestValidation::test_last_role_assistant, backend/tests/test_ai_views_chat.py::TestValidation::test_first_role_assistant, backend/tests/test_ai_views_chat.py::TestValidation::test_max_turns_plus_one_rejected, backend/tests/test_ai_views_chat.py::TestValidation::test_max_turns_boundary_equal_passes

#### Scenario: Content limits
- **WHEN** any `content` is not a string, is blank or whitespace-only, exceeds `LLM_MAX_COMMAND_CHARS`, or the sum of all content lengths exceeds `LLM_CHAT_MAX_TOTAL_CHARS`
- **THEN** the response is 400; a sum exactly at the cap is accepted

Tests: backend/tests/test_ai_views_chat.py::TestValidation::test_per_message_cap, backend/tests/test_ai_views_chat.py::TestValidation::test_total_chars_cap, backend/tests/test_ai_views_chat.py::TestValidation::test_total_chars_cap_boundary_equal_passes, backend/tests/test_ai_response_history.py::test_blank_transcript_content_rejected_before_provider

#### Scenario: Rejected body has no side effects
- **WHEN** a request fails transcript validation
- **THEN** no Schedule row is created and the chat rate-limit counter is unchanged

Tests: backend/tests/test_ai_views_chat.py::TestValidation::test_invalid_body_does_not_create_schedule, backend/tests/test_ai_views_chat.py::TestValidation::test_validation_failures_do_not_consume_rate_limit

### Requirement: Assistant turn markers
The system SHALL accept the optional `is_ask` and `is_error` booleans and the `applied_add_block_ids` list only on assistant turns, and SHALL reject other placements or types with 400. The markers are hints for the replay and relative-add guards, not an authorization boundary.
Enforced: backend/ai/views.py::_validate_chat_messages

#### Scenario: Marker type or placement is wrong
- **WHEN** `is_ask` or `is_error` is not a boolean, or any marker appears on a user turn
- **THEN** the response is 400 `errors.messages`; a boolean `is_ask` on an assistant turn is accepted

Tests: backend/tests/test_ai_views_chat.py::TestValidation::test_is_ask_must_be_boolean, backend/tests/test_ai_views_chat.py::TestValidation::test_is_error_must_be_boolean, backend/tests/test_ai_views_chat.py::TestValidation::test_flags_rejected_on_user_turns, backend/tests/test_ai_views_chat.py::TestValidation::test_is_ask_true_accepted

#### Scenario: Applied block IDs are bounded
- **WHEN** `applied_add_block_ids` is not a list of positive integers (booleans excluded) or has more than 20 entries
- **THEN** the response is 400 `errors.messages`

Tests: backend/tests/test_ai_views_chat.py::TestValidation::test_applied_add_ids_rejected_on_user_or_with_invalid_values

### Requirement: Durable request identity
The system SHALL require a canonical UUID `request_id` and bind it to the SHA-256 of the whole canonical JSON body within the namespace owner + civil date. A completed identity SHALL replay its stored status and body without a provider call, rate-limit token or write.
Enforced: backend/ai/chat_requests.py::request_identity, backend/ai/chat_requests.py::claim_request

#### Scenario: Missing or non-canonical identity
- **WHEN** `request_id` is absent, not a string, or not the canonical lowercase UUID form
- **THEN** the response is 400 `errors.request_id` and no claim, Schedule row or rate-limit token is used

Tests: backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_invalid_identity_does_not_write_or_charge, backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_missing_identity_is_rejected_by_real_client

#### Scenario: Lost response is retried
- **WHEN** a completed request is resent with the same identity and body, even with a now-stale revision or after the clock or gap preference moved
- **THEN** the stored status and bytes are returned with `request_completed: true`, and the provider is not called again

Tests: backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_lost_response_replays_exact_result_before_stale_revision, backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_tight_window_result_replays_after_clock_advances, backend/tests/test_ai_chat_requests.py::test_completed_receipt_replays_after_gap_change

#### Scenario: Same identity with a different body
- **WHEN** a request reuses an identity with a different body hash
- **THEN** the response is 409 with `code` `request_id_conflict`

Tests: backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_identity_binds_entire_body

#### Scenario: Namespaces are per owner and date
- **WHEN** the same UUID is used by another user or for another date
- **THEN** it is treated as an independent new request

Tests: backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_other_owner_and_date_have_independent_namespaces

#### Scenario: Identity outlives the day
- **WHEN** the Schedule row is deleted after a request completed
- **THEN** the same identity still replays the stored result

Tests: backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_completed_identity_survives_schedule_deletion

### Requirement: Fenced lease and atomic terminal receipt
The system SHALL give each claim a lease token and store the terminal status and body in the same transaction as any schedule writes. Only the current lease holder may commit, and every terminal body SHALL carry `request_id` and `request_completed: true`.
Enforced: backend/ai/chat_requests.py::claim_request, backend/ai/chat_requests.py::finish_request

#### Scenario: Request still in flight
- **WHEN** an identical request arrives while an unexpired lease is held
- **THEN** the response is 409 `request_in_progress` with `Retry-After: 2`

Tests: backend/tests/test_ai_chat_requests.py::test_expired_worker_cannot_apply_after_takeover

#### Scenario: Expired worker after takeover
- **WHEN** a lease expires, another worker takes it over, and the original worker tries to finish
- **THEN** the original worker's result is not applied; it gets 409 or the winner's stored result

Tests: backend/tests/test_ai_chat_requests.py::test_expired_worker_cannot_apply_after_takeover, backend/tests/test_ai_chat_requests.py::test_two_processes_send_same_http_request

#### Scenario: Lock contention while storing
- **WHEN** the user-lock maintenance step raises a retryable schedule-changed condition during claim or finish
- **THEN** the response is 503 `request_unavailable` and the request stays uncompleted

Tests: backend/tests/test_ai_chat_requests.py::test_schedule_changed_while_applying_is_unavailable_not_a_terminal_500

#### Scenario: Receipt storage fails
- **WHEN** storing the receipt fails after the plan was built
- **THEN** the schedule writes roll back with it and a later retry can recover

Tests: backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_receipt_storage_failure_rolls_back_schedule_then_can_recover

### Requirement: Terminal errors are stored receipts
The system SHALL store provider failures, rate-limit rejections and unexpected exceptions as terminal receipts for the identity. An unexpected non-AI exception SHALL return a generic 500 whose body never contains the exception text.
Enforced: backend/ai/views.py::ai_chat, backend/ai/chat_requests.py::unexpected_error_response

#### Scenario: Provider error
- **WHEN** the provider call fails with an AI error
- **THEN** the same identity replays the identical error without another call, and a new UUID can retry

Tests: backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_provider_error_is_terminal_and_new_id_can_retry

#### Scenario: Unexpected exception
- **WHEN** a non-AI exception occurs during the provider call or while applying the result
- **THEN** the response is 500 with a generic detail, any partial plan is rolled back, and the receipt is completed

Tests: backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_unexpected_provider_exception_is_terminal_without_leaking_detail, backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_unexpected_exception_while_applying_result_is_terminal_and_rolled_back

### Requirement: Revision and policy context fencing
The system SHALL require `expected_revision` to match before the provider call, and SHALL re-check revision and a context fingerprint under the write lock before applying or returning any 200 turn. A mismatch returns 409 `schedule_changed`.
Enforced: backend/ai/views.py::_load_ai_context_sync, backend/ai/views.py::_apply_actions_sync

#### Scenario: Stale or invalid revision
- **WHEN** `expected_revision` is missing, invalid or differs from the stored revision
- **THEN** the response is 409 `schedule_changed` and the provider is not called

Tests: backend/tests/test_ai_revision.py::test_ai_and_active_review_require_valid_revision, backend/tests/test_ai_revision.py::test_ai_conflict_on_absent_day_does_not_create_any_context

#### Scenario: Context changes during the provider call
- **WHEN** blocks, active rules, categories, window, time zone or the default block gap change while the provider runs
- **THEN** the response is 409 `schedule_changed` and the model output is not applied

Tests: backend/tests/test_ai_views_chat.py::TestChatBatchMutationExecutor::test_chat_apply_returns_409_when_schedule_changes_during_run_chat, backend/tests/test_ai_views_chat.py::TestChatBatchMutationExecutor::test_chat_apply_returns_409_when_rule_changes_during_run_chat, backend/tests/test_ai_revision.py::test_ai_rejects_prompt_policy_changes, backend/tests/test_ai_views_chat.py::test_chat_gap_context_changes, backend/tests/test_ai_views_chat.py::TestChatStoredTimezone::test_apply_rejects_timezone_changed_via_settings_api_during_prompt

#### Scenario: No-op turn after a context change
- **WHEN** the model returns no actions but the context changed during the call
- **THEN** the response is still 409 `schedule_changed`

Tests: backend/tests/test_ai_views_chat.py::TestChatBatchMutationExecutor::test_chat_empty_actions_rejects_changed_context

### Requirement: Chat rate limit
The system SHALL consume one token from the per-user `ai_chat_rl` fixed-window counter (`LLM_CHAT_RATE_LIMIT_PER_HOUR`) after context capture and before the provider call, independently of the draft counter. An exhausted budget returns 429 with `Retry-After: 3600`.
Enforced: backend/ai/views.py::ai_chat, backend/ai/views.py::_consume_rate_limit

#### Scenario: Budget exhausted
- **WHEN** a user exceeds the hourly chat budget
- **THEN** the response is 429 with the standard rate-limit detail, and no audit row is written for it

Tests: backend/tests/test_ai_views_chat.py::TestRateLimit::test_chat_bucket_enforces_limit

#### Scenario: Independent of the draft bucket
- **WHEN** a chat request is admitted
- **THEN** only `ai_chat_rl` is incremented

Tests: backend/tests/test_ai_views_chat.py::TestRateLimit::test_chat_bucket_independent_of_draft_bucket

#### Scenario: Explicit cancel is free
- **WHEN** a request carries `intent_action: "cancel"` for an open pending intent
- **THEN** it completes without calling the provider or consuming the rate limit

Tests: backend/tests/test_ai_pending_intents.py::test_explicit_cancel_is_provider_independent_and_replayable

### Requirement: Startup check for the shared rate-limit cache
The system SHALL fail the `ai.E001` system check whenever `LLM_API_KEY` is set and `CACHES['default']` uses LocMem, FileBased or Dummy cache, regardless of `DEBUG`.
Enforced: backend/ai/checks.py::error_locmem_cache_with_ai_in_production

#### Scenario: AI enabled on an ineffective cache
- **WHEN** `LLM_API_KEY` is set and the default cache is LocMem, FileBased or Dummy
- **THEN** the check returns error `ai.E001`

Tests: backend/tests/test_checks.py::TestLocmemCacheProductionError::test_errors_when_prod_plus_locmem_plus_ai, backend/tests/test_checks.py::TestLocmemCacheProductionError::test_errors_when_prod_plus_filebased_plus_ai, backend/tests/test_checks.py::TestLocmemCacheProductionError::test_errors_when_dummy_plus_ai

#### Scenario: AI disabled
- **WHEN** `LLM_API_KEY` is empty
- **THEN** the check reports nothing

Tests: backend/tests/test_checks.py::TestLocmemCacheProductionError::test_silent_when_ai_disabled

### Requirement: Provider error mapping
The system SHALL map AI failures to HTTP statuses: missing `LLM_API_KEY` 503, provider timeout 504, provider or client-init error 502, parse error 502, invalid service input 400. A parse error SHALL return a fixed generic detail; other errors return their own message.
Enforced: backend/ai/views.py::_AI_ERROR_STATUS, backend/ai/service.py::run_chat

#### Scenario: Status per error class
- **WHEN** the service raises unavailable, timeout, provider, invalid-input or parse errors
- **THEN** the response status is 503, 504, 502, 400 or 502 respectively

Tests: backend/tests/test_ai_views_chat.py::TestAuditEnvelope::test_failure_envelope_carries_error_class, backend/tests/test_ai_service_chat.py::TestInputGuards::test_missing_api_key_raises_unavailable, backend/tests/test_ai_service_chat.py::TestProviderErrors::test_timeout_maps_to_ai_timeout, backend/tests/test_ai_service_chat.py::TestProviderErrors::test_api_error_maps_to_provider, backend/tests/test_ai_service_chat.py::TestProviderErrors::test_unexpected_exception_maps_to_provider

#### Scenario: Parse error detail is generic
- **WHEN** the provider reply fails JSON parsing or validation
- **THEN** the client sees the fixed "couldn't be applied" detail and the real validation message is kept only in the audit row

Tests: backend/tests/test_ai_views_chat.py::TestAuditEnvelope::test_failure_envelope_carries_error_class, backend/tests/test_ai_service_chat.py::TestParsing::test_invalid_json_raises_parse

#### Scenario: Client initialization failure
- **WHEN** constructing the provider client raises
- **THEN** a provider error is raised without chaining the original exception

Tests: backend/tests/test_ai_service_client.py::TestClientPerLoop::test_init_failure_raises_provider_error

### Requirement: Provider call parameters
The system SHALL call the chat-completions API with `LLM_MODEL`, JSON-object response format, temperature 0 and `LLM_REQUEST_TIMEOUT`, using the user's stored time zone for the local time in the prompt. Client-supplied time zones are ignored.
Enforced: backend/ai/service.py::run_chat, backend/ai/views.py::ai_chat

#### Scenario: Stored time zone drives local time
- **WHEN** a user with a stored IANA zone sends a chat turn, with or without a client time-zone field
- **THEN** the prompt's current local time is computed in the stored zone

Tests: backend/tests/test_ai_views_chat.py::TestChatStoredTimezone::test_chat_prompt_uses_stored_timezone, backend/tests/test_ai_views_chat.py::TestChatStoredTimezone::test_client_timezone_is_ignored_in_favor_of_stored_zone

### Requirement: Untrusted prior transcript
The system MUST NOT forward client-supplied prior turns under the `assistant` role. Prior turns SHALL be JSON-encoded into one user-role message under an untrusted-transcript header, separate from the latest user turn. Turn markers are never sent to the provider.
Enforced: backend/ai/service.py::run_chat, backend/ai/prompts.py::serialise_prior_turns

#### Scenario: Tampered assistant turn
- **WHEN** the transcript contains assistant turns
- **THEN** the provider receives only system and user role messages, with prior assistant turns labelled as claimed text

Tests: backend/tests/test_ai_service_chat.py::TestUntrustedTranscript::test_assistant_role_never_forwarded, backend/tests/test_ai_service_chat.py::TestUntrustedTranscript::test_transcript_warning_marker_present

#### Scenario: Latest turn kept separate
- **WHEN** a multi-turn transcript is sent
- **THEN** the latest user turn is its own final user message and `is_ask`, `is_error` and `applied_add_block_ids` never appear in provider content

Tests: backend/tests/test_ai_service_chat.py::TestUntrustedTranscript::test_latest_user_turn_is_separate_message, backend/tests/test_ai_service_chat.py::TestUntrustedTranscript::test_turn_flags_never_forwarded_to_provider

### Requirement: Transcript egress per turn
The system SHALL send the full prior client transcript to the provider on every turn, with two exceptions: a continuation of a server-owned pending intent sends an empty prior transcript plus the saved pending summary, and a continuation reclassified as a new command is re-sent with only the latest turn.
Enforced: backend/ai/service.py::run_chat, backend/ai/views.py::ai_chat

#### Scenario: Pending continuation
- **WHEN** a request continues an open pending intent
- **THEN** the provider context carries the saved source message, question and pending actions, and no client prior turns

Tests: backend/tests/test_ai_service_chat.py::TestServerOwnedPendingContext::test_uses_saved_scope_without_the_client_transcript

#### Scenario: Continuation turns out to be a new command
- **WHEN** a continuation reply is classified `intent_decision: "new"`
- **THEN** the provider is called again with only the latest user turn and no pending summary

Tests: backend/tests/test_ai_pending_intents.py::test_explicit_new_command_is_reinterpreted_without_pending_or_transcript

### Requirement: Protected block titles are masked for the provider
The system SHALL replace titles of blocks whose origin is not `manual` (calendar imports and unknown-origin restores) with `[private block]` in the schedule context, in provider-bound transcript text and in the pending summary, while keeping times, category and completion.
Enforced: backend/ai/prompts.py::_runtime_block_to_dict, backend/ai/service.py::run_chat

#### Scenario: Imported title echoed in the transcript
- **WHEN** a calendar-imported block exists and its title appears in a prior turn
- **THEN** neither the context nor the provider transcript contains that title; local transcript and replay evidence are unchanged

Tests: backend/tests/test_ai_calendar_privacy.py::test_imported_title_is_absent_from_chat_context_and_echoed_transcript, backend/tests/test_ai_service_chat.py::TestServerOwnedPendingContext::test_pending_summary_redacts_imported_titles

#### Scenario: Manual block with the same title
- **WHEN** only a manual block carries a title
- **THEN** that title stays visible in the context

Tests: backend/tests/test_ai_calendar_privacy.py::test_manual_block_with_same_title_remains_visible_in_context

### Requirement: Trusted schedule context
The system SHALL put the schedule date, weekday, current local time, existing blocks and the user's own active rules (priority descending, JSON-encoded) in a server-built user message, not in the transcript block.
Enforced: backend/ai/prompts.py::build_chat_user_message, backend/ai/prompts.py::_format_rules_section

#### Scenario: Only the caller's active rules
- **WHEN** the user and another user both have rules, some inactive
- **THEN** only the caller's active rules are passed, in priority order

Tests: backend/tests/test_ai_views_chat.py::TestActiveRulesWiring::test_only_authenticated_users_active_rules_are_passed, backend/tests/test_ai_service_chat.py::TestRulesWiring::test_rule_appears_in_first_user_context_message

#### Scenario: Rule text cannot reshape the prompt
- **WHEN** a rule contains quotes, newlines or prompt-like labels
- **THEN** it is JSON-encoded on one line inside the schedule context, outside the transcript

Tests: backend/tests/test_ai_prompts_command_chat.py::TestFormatRulesSection::test_malicious_rule_text_is_safely_encoded, backend/tests/test_ai_prompts_command_chat.py::TestBuildChatUserMessage::test_rule_present_in_schedule_context_not_transcript

### Requirement: Reply envelope validation
The system SHALL reject a provider reply with a parse error unless it is a JSON object with an `actions` array of at most 20 items, a string `explanation` within `LLM_MAX_EXPLANATION_CHARS`, and an `ask` key that is null or nonblank within `LLM_CHAT_MAX_ASK_CHARS`.
Enforced: backend/ai/schemas.py::validate_chat_response_envelope

#### Scenario: Ask and actions together
- **WHEN** the reply has a non-empty `ask` and non-empty `actions`
- **THEN** it fails with a parse error

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_rejects_ask_with_actions

#### Scenario: Blank or oversized fields
- **WHEN** `ask` is empty or whitespace, `ask` or `explanation` exceeds its cap, or `explanation` is blank while `ask` is null
- **THEN** it fails with a parse error before any action is applied

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_rejects_empty_string_ask, backend/tests/test_ai_service_chat.py::TestParsing::test_rejects_whitespace_ask, backend/tests/test_ai_service_chat.py::TestParsing::test_rejects_overlong_ask, backend/tests/test_ai_service_chat.py::TestParsing::test_rejects_overlong_explanation, backend/tests/test_ai_service_chat.py::TestParsing::test_rejects_blank_explanation_without_ask, backend/tests/test_ai_response_history.py::test_blank_no_ask_reply_rejected_before_mutation

#### Scenario: Reply must fit the next turn
- **WHEN** the `ask`, or the `explanation` when ask is null, is longer than `LLM_MAX_COMMAND_CHARS`
- **THEN** it fails with a parse error; an ask with a blank explanation is accepted

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_rejects_reply_longer_than_next_turn_content_limit, backend/tests/test_ai_service_chat.py::TestParsing::test_accepts_ask_with_blank_explanation

### Requirement: Question recovery for add turns
The system SHALL promote a reply's `explanation` to `ask` only when the latest provider-bound turn starts with an add command, `actions` is empty, `ask` is null, and the explanation is one standalone question that is not a conversational closer.
Enforced: backend/ai/service.py::run_chat, backend/ai/service.py::_is_recoverable_chat_question

#### Scenario: Question in explanation on an add turn
- **WHEN** the user asked to add something and the model returns a single question in `explanation` with null `ask`
- **THEN** the question becomes `ask`

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_no_action_question_in_explanation_becomes_ask, backend/tests/test_ai_service_chat.py::TestParsing::test_polite_and_russian_adds_recover_questions

#### Scenario: Closers and other turns are not recovered
- **WHEN** the explanation is a status plus a polite closer such as "anything else?", or the latest turn is not an add command
- **THEN** `ask` stays null

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_conversational_question_does_not_become_pending_ask, backend/tests/test_ai_service_chat.py::TestParsing::test_cancellation_closer_does_not_become_pending_ask, backend/tests/test_ai_service_chat.py::TestParsing::test_closing_pending_ask_does_not_recover_polite_question

#### Scenario: Recovered question still obeys limits
- **WHEN** the recovered question exceeds the ask cap
- **THEN** the reply fails envelope validation

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_recovered_question_still_obeys_ask_length_limit

### Requirement: Intent decision field
The system SHALL accept an optional `intent_decision` of `new`, `continue`, `cancel` or `read` and reject any other value with a parse error. A `cancel` or `read` decision SHALL discard the reply's actions and ask.
Enforced: backend/ai/service.py::run_chat, backend/ai/views.py::ai_chat

#### Scenario: Unknown decision
- **WHEN** `intent_decision` is not one of the four values
- **THEN** the reply fails with a parse error

Tests: backend/tests/test_ai_service_chat.py::TestServerOwnedPendingContext::test_invalid_decision_is_rejected

#### Scenario: Non-mutating decision with actions
- **WHEN** the reply says `cancel` or `read` but also lists actions
- **THEN** no actions are applied

Tests: backend/tests/test_ai_service_chat.py::TestServerOwnedPendingContext::test_nonmutating_decisions_cannot_smuggle_actions, backend/tests/test_ai_pending_intents.py::test_read_classification_discards_actions_but_retains_unresolved_work

### Requirement: Success response envelope
The system SHALL return every 200 chat turn with the schedule snapshot plus `explanation`, `ask`, `applied`, `partial`, `outcomes` and `pending_intent`. Turns that write nothing (ask, chit-chat, guard) return `blocks: null`, `applied: false`, and empty `outcomes` except for the replay guard.
Enforced: backend/ai/views.py::_finish_chat_sync, backend/ai/pending_intents.py::finish

#### Scenario: Clarifying question
- **WHEN** the model returns a non-null `ask`
- **THEN** nothing is written, the ask is returned with `blocks: null` and `applied: false`

Tests: backend/tests/test_ai_views_chat.py::TestClarifyingQuestion::test_returns_ask_without_mutating

#### Scenario: Chit-chat
- **WHEN** the model returns no actions, null ask and no unresolved category
- **THEN** the explanation is returned with `ask: null`, `applied: false`, `partial: false` and `outcomes: []`

Tests: backend/tests/test_ai_views_chat.py::TestApply::test_chitchat_no_op, backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_empty_outcomes_are_preserved_in_audit_and_receipt

#### Scenario: Applied turn
- **WHEN** at least one action is planned
- **THEN** the response carries the new snapshot, `applied` true when any create, update or delete was persisted, and one outcome per action

Tests: backend/tests/test_ai_views_chat.py::TestApply::test_apply_actions_creates_blocks

#### Scenario: Partial flag
- **WHEN** an applied turn leaves unresolved work for a pending intent
- **THEN** `partial` is true whenever something was applied; otherwise it reflects whether the plan was partial

Tests: backend/tests/test_ai_pending_intents.py::test_partial_plan_without_model_question_keeps_scope_and_accepted_ids

### Requirement: Chat audit log
The system SHALL write one best-effort `AIInteraction` row of kind `chat` per admitted request whose provider call returns or raises an AI error. `user_command` is the latest user turn verbatim (first 2000 chars); `ai_response` is JSON with the transcript hash, turn count and raw reply, capped at 10000 chars.
Enforced: backend/ai/views.py::_build_chat_audit_response, backend/ai/views.py::_log_interaction

#### Scenario: Success row
- **WHEN** a turn completes with 200 and is not a replay
- **THEN** the row has `success` true, `outcomes_json` set to the response outcomes, `actions_json` set to the normalized actions, and no `error_class`

Tests: backend/tests/test_ai_views_chat.py::TestAuditEnvelope::test_success_envelope_has_transcript_hash, backend/tests/test_ai_chat_requests.py::TestChatRequestHTTP::test_empty_outcomes_are_preserved_in_audit_and_receipt

#### Scenario: Failure row
- **WHEN** the provider attempt raises an AI error
- **THEN** the row has `success` false, empty `actions_json`, `error_class`, and for parse errors an `error_detail` placed before `raw`

Tests: backend/tests/test_ai_views_chat.py::TestAuditEnvelope::test_failure_envelope_carries_error_class, backend/tests/test_ai_views_chat.py::TestSharedApplyCoverage::test_log_truncates_oversized_response

#### Scenario: Rewritten turn is logged as typed
- **WHEN** the latest turn was rewritten as an implicit add for the provider
- **THEN** the audit `user_command` and transcript hash use the original text

Tests: backend/tests/test_ai_views_chat.py::TestImplicitAddAuditUnaffected::test_audit_user_command_keeps_original_text

#### Scenario: Rejected or failed apply stays unsuccessful
- **WHEN** the apply step returns a non-200 response
- **THEN** the row keeps `success` false

Tests: backend/tests/test_ai_views_chat.py::TestChatBatchMutationExecutor::test_chat_empty_actions_rejects_changed_context
