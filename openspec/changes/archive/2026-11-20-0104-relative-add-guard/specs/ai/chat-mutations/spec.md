## MODIFIED Requirements

### Requirement: Relative add guard
The system SHALL NOT auto-place an add requested before or after an existing block. Such a turn SHALL return a server question unless each checked add is timed on the correct side of the one resolved anchor and any stated gap, or a clock reply with every add timed answers a question with no single anchor. "One after another" is not a relation.
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
- **THEN** the response asks which block; the newest reply naming exactly one block outside a start clause ("Vocal starts at 0945") resolves it

Tests: backend/tests/test_ai_relative_add_guard.py::test_unknown_reference_asks_which_block, backend/tests/test_ai_relative_add_guard.py::test_answer_naming_a_block_resolves_unknown_anchor, backend/tests/test_ai_relative_add_guard.py::test_newest_reply_overrides_an_earlier_answer

#### Scenario: Russian request
- **WHEN** the request or the latest reply contains Cyrillic
- **THEN** the question is in Russian

Tests: backend/tests/test_ai_relative_add_guard.py::test_russian_requests_get_russian_questions, backend/tests/test_ai_relative_add_guard.py::test_english_request_with_russian_reply_gets_russian_question

#### Scenario: Sequential idiom
- **WHEN** a request orders the new blocks among themselves ("one after another", "один после другого", "друг после друга")
- **THEN** the idiom is not a placement relation and the turn applies normally

Tests: backend/tests/test_ai_relative_add_guard.py::test_sequence_idiom_is_not_an_existing_block_relation, backend/tests/test_ai_relative_guard_recovery.py::test_sequence_multi_add_applies_without_guard_question

#### Scenario: Idiom beside a genuine anchor
- **WHEN** the same request also places the adds after or before an existing block
- **THEN** that relation is still enforced

Tests: backend/tests/test_ai_relative_add_guard.py::test_sequence_idiom_preserves_external_anchor, backend/tests/test_ai_relative_add_guard.py::test_russian_sequence_words_keep_a_real_relation

#### Scenario: Natural clock answer
- **WHEN** a reply to a question with no single anchor gives a clock time ("09:45", "0945", "в 09:45", "Vocal starts at 0945") and every add is timed
- **THEN** the guard asks nothing; a resolved anchor still constrains the answer

Tests: backend/tests/test_ai_relative_add_guard.py::test_natural_clock_answer_resolves_unbound_relation, backend/tests/test_ai_relative_add_guard.py::test_clock_answers_accepted_today_stay_accepted, backend/tests/test_ai_relative_add_guard.py::test_clock_answer_resolves_multi_relation_time_question, backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_accepts_natural_clock_answer, backend/tests/test_ai_relative_guard_recovery.py::test_multi_relation_guard_question_can_be_answered, backend/tests/test_ai_relative_guard_recovery.py::test_relative_guard_round_trip_through_provider_parser

#### Scenario: Start clause names the new block
- **WHEN** a reply such as "Vocal starts at 0945" names an existing block that has the new block's title
- **THEN** it is not an anchor answer, also after a sibling was applied; a block named outside the clause still binds

Tests: backend/tests/test_ai_relative_add_guard.py::test_start_clause_about_the_new_block_is_not_an_anchor, backend/tests/test_ai_relative_add_guard.py::test_start_clause_stays_a_start_clause_after_partial_completion, backend/tests/test_ai_relative_guard_recovery.py::test_start_clause_stays_a_start_clause_after_partial_completion_endpoint

#### Scenario: Clock answer cannot bypass a constraint
- **WHEN** the reply is a duration, an invalid or embedded number, an untimed add, or a time on the wrong side of a resolved anchor or gap, or several anchors are named
- **THEN** the guard still asks

Tests: backend/tests/test_ai_relative_add_guard.py::test_clock_answer_does_not_bypass_relative_constraints
