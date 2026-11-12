# ai/chat-intents Specification

## Purpose
A chat turn that ends with a question, or leaves part of a request unresolved, stores a server-owned pending intent. A later turn may continue it only within the saved scope: the missing fields and target choices recorded on the server, not anything the client transcript claims. Intent state, schedule writes and the request receipt commit in one transaction. The request contract is in `ai/chat` and the mutation rules are in `ai/chat-mutations`.

## Requirements

### Requirement: Pending intent reference validation
The system SHALL accept `pending_intent_id`, `pending_intent_version` and `intent_action` only as a canonical UUID, a positive integer version and one of `new`, `continue` or `cancel`, and SHALL reject anything else with 400 `errors.pending_intent` before any write.
Enforced: backend/ai/pending_intents.py::parse_reference, backend/ai/views.py::ai_chat

#### Scenario: Malformed reference
- **WHEN** the id is not a canonical UUID, the version is missing or a boolean, the id is missing, or `cancel` is sent without a reference
- **THEN** the response is 400 and no Schedule row or request claim is created

Tests: backend/tests/test_ai_pending_intents.py::test_invalid_reference_does_not_write

### Requirement: Pending intent creation
The system SHALL store a server-owned pending intent whenever a 200 turn ends with an ask: one open record per owner and schedule, with the source message, question, bounded item scope, accepted block IDs, revision, post-write fingerprint and a fixed 15-minute expiry, returned as `pending_intent`.
Enforced: backend/ai/pending_intents.py::finish, backend/ai/pending_intents.py::validate_items, backend/ai/models.py::PendingIntent

#### Scenario: Question recorded
- **WHEN** a turn returns a clarifying question
- **THEN** a pending intent with version 1 is created and the response carries its id, version, expiry and ask

Tests: backend/tests/test_ai_pending_intents.py::test_question_is_durable_and_replay_does_not_replace_it

#### Scenario: Unresolved work without a model question
- **WHEN** a plan applies part of a request and leaves work unresolved, but the model asked nothing
- **THEN** the response carries a generic pending question, `partial: true`, and an open intent holding the accepted block IDs

Tests: backend/tests/test_ai_pending_intents.py::test_partial_plan_without_model_question_keeps_scope_and_accepted_ids

#### Scenario: Scope stays bounded
- **WHEN** model-proposed pending actions name targets outside the schedule or invalid fields
- **THEN** they are rejected and cannot grant new targets

Tests: backend/tests/test_ai_service_chat.py::TestServerOwnedPendingContext::test_pending_targets_are_owned, backend/tests/test_ai_pending_intents.py::test_target_choices_and_known_fields_are_bounded

### Requirement: Pending intent continuation
The system SHALL let a request referencing an open intent by id and version apply only actions that answer saved missing fields within saved targets, each permission once. Expanded actions return 409 `pending_intent_scope`; a stale, expired or changed-context intent returns 409 `pending_intent_stale` before the provider call.
Enforced: backend/ai/pending_intents.py::capture, backend/ai/pending_intents.py::finish

#### Scenario: Answer resolves once
- **WHEN** the user answers the pending question within its scope
- **THEN** the change applies, the intent becomes resolved and a second answer returns 409

Tests: backend/tests/test_ai_pending_intents.py::test_answer_uses_server_scope_and_resolves_once, backend/tests/test_ai_pending_concurrency.py::test_two_processes_answer_one_intent

#### Scenario: Reply widens the scope
- **WHEN** the reply's actions go beyond the saved targets or fields
- **THEN** the response is 409 `pending_intent_scope`, nothing is written and the intent stays open

Tests: backend/tests/test_ai_pending_intents.py::test_expanded_actions_are_rejected_atomically, backend/tests/test_ai_pending_intents.py::test_repeated_question_cannot_expand_target_or_fields

#### Scenario: Stale or foreign intent
- **WHEN** the intent is closed, expired, of another owner or day, has an old version, or the schedule or policy context changed
- **THEN** the response is 409 `pending_intent_stale` without a provider call or rate-limit token, and an outdated intent is marked stale

Tests: backend/tests/test_ai_pending_intents.py::test_stale_or_foreign_scope_does_not_call_provider, backend/tests/test_ai_pending_intents.py::test_gap_change_invalidates_pending_intent, backend/tests/test_ai_pending_intents.py::test_deleted_schedule_is_not_recreated_by_an_old_intent

#### Scenario: Follow-up question
- **WHEN** a continuation ends with another question
- **THEN** the same intent's version increases, unanswered siblings are retained, and the expiry is not extended

Tests: backend/tests/test_ai_pending_intents.py::test_ask_only_turn_advances_version_without_extending_expiry, backend/tests/test_ai_pending_intents.py::test_remaining_sibling_is_retained_after_one_answer

### Requirement: Pending intent cancellation
The system SHALL cancel an open intent on `intent_action: "cancel"` without calling the provider, or when the model classifies the reply as `cancel`. Cancellation writes no schedule change and returns "Pending request cancelled." with `pending_intent: null`.
Enforced: backend/ai/pending_intents.py::finish, backend/ai/views.py::ai_chat

#### Scenario: Explicit cancel
- **WHEN** the client sends `intent_action: "cancel"` for the open intent
- **THEN** the intent becomes cancelled, the revision is unchanged and the result replays for the same request id

Tests: backend/tests/test_ai_pending_intents.py::test_explicit_cancel_is_provider_independent_and_replayable

#### Scenario: Free-text cancel with stray actions
- **WHEN** the model classifies a reply as cancel but also returns actions
- **THEN** no actions apply and the intent becomes cancelled

Tests: backend/tests/test_ai_pending_intents.py::test_free_text_cancel_discards_even_incorrect_model_actions
