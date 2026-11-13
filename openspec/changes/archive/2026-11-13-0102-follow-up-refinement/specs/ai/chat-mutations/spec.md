## MODIFIED Requirements

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

## ADDED Requirements

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
