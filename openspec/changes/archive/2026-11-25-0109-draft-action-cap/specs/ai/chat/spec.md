## MODIFIED Requirements

### Requirement: Reply envelope validation
The system SHALL reject a provider reply with a parse error unless it is a JSON object with an `actions` array of at most `MAX_ACTIONS_PER_COMMAND` (20) items, separate from the draft cap, a string `explanation` within `LLM_MAX_EXPLANATION_CHARS`, and an `ask` key that is null or nonblank within `LLM_CHAT_MAX_ASK_CHARS`.
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

#### Scenario: More than 20 actions
- **WHEN** the reply has 21 actions
- **THEN** it fails with a parse error, while 20 actions pass

Tests: backend/tests/test_ai_service_chat.py::TestParsing::test_chat_action_cap_stays_at_twenty
