## MODIFIED Requirements

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

#### Scenario: Relative-add guard question
- **WHEN** the relative-add guard asks instead of placing an add
- **THEN** the schedule is unchanged, the response has `blocks: null`, `applied: false`, `partial: false`, empty `outcomes` and an opaque `pending_intent`, and its saved scope stays private; replaying the request returns the same bytes

Tests: backend/tests/test_ai_relative_guard_recovery.py::test_fresh_relative_guard_saves_scope_and_accepts_anchor_answer
