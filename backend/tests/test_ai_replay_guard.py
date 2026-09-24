"""Unit tests for ``ai.replay_guard`` (feature 0083, issue #219).

Pure module — stdlib only, no Django, no DB. See
``docs/features/0083_PLAN.md`` §B2 for the algorithm this pins.
"""

from ai.replay_guard import GUARD_ASK_PREFIX, REPLAY_GUARD_REASON_CODE, find_replayed_actions


def _u(text, **flags):
    return {"role": "user", "content": text, **flags}


def _a(text, **flags):
    return {"role": "assistant", "content": text, **flags}


def _add(title):
    return {"type": "add", "title": title}


class TestConstants:
    def test_reason_code(self):
        assert REPLAY_GUARD_REASON_CODE == "replay_guard"

    def test_ask_prefix(self):
        assert GUARD_ASK_PREFIX == "I did not change the schedule:"


class TestSuffixStrippingAndNormalisation:
    def test_numeric_suffix_flagged_as_replay(self):
        messages = [_u("add Momentum (Personal)"), _a("Added Momentum"), _u("Notes")]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)

    def test_numeric_suffix_with_space_flagged(self):
        messages = [_u("add Momentum"), _a("Added Momentum"), _u("Notes")]
        assert find_replayed_actions([_add("Momentum [12]")], messages) == (0,)

    def test_bracketed_non_numeric_suffix_not_stripped(self):
        # "GridBot[Note]" is not a duplicate-counter suffix — kept whole, and
        # the whole string ("gridbot[note]") never appears in the prior text,
        # so this is a first-time title, not a replay.
        messages = [_u("add Momentum"), _a("Added Momentum"), _u("add GridBot[Note]")]
        assert find_replayed_actions([_add("GridBot[Note]")], messages) == ()

    def test_case_and_whitespace_normalised(self):
        messages = [_u("add momentum"), _a("Added momentum"), _u("Notes")]
        assert find_replayed_actions([_add("  MOMENTUM  ")], messages) == (0,)


class TestStepATraceability:
    def test_any_token_overlap_allows_rule_driven_naming(self):
        messages = [_u("Gym Session"), _a("Added Gym Session"), _u("add gym")]
        assert find_replayed_actions([_add("Gym Session")], messages) == ()

    def test_digit_only_latest_turn_never_counts_as_traceable(self):
        messages = [_u("add Momentum"), _a("Momentum does not fit."), _u("14:00")]
        assert find_replayed_actions([_add("Momentum")], messages) == (0,)

    def test_cyrillic_traceable(self):
        messages = [_u("добавь обед"), _a("Added"), _u("обед")]
        assert find_replayed_actions([_add("Обед")], messages) == ()

    def test_cyrillic_not_traceable_is_flagged(self):
        messages = [_u("добавь Обед"), _a("Added"), _u("Заметки")]
        assert find_replayed_actions([_add("Обед")], messages) == (0,)

    def test_step_b_needs_evidence(self):
        messages = [_u("something else"), _a("ok"), _u("Обед")]
        assert find_replayed_actions([_add("Lunch")], messages) == ()

    def test_vacuous_title_never_flagged(self):
        messages = [_u("add Momentum"), _a("Added Momentum"), _u("Notes")]
        assert find_replayed_actions([_add("🏋️")], messages) == ()

    def test_single_message_transcript_never_flagged(self):
        messages = [_u("add Momentum[2]")]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == ()


class TestIsAskSkipsGuard:
    def test_is_ask_true_skips_guard_even_for_textbook_replay(self):
        messages = [
            _u("add Momentum (Personal)"),
            _a("What would you like to add?", is_ask=True),
            _u("Notes"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == ()

    def test_is_ask_false_still_flags(self):
        messages = [
            _u("add Momentum (Personal)"),
            _a("Added Momentum", is_ask=False),
            _u("Notes"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)

    def test_is_ask_absent_still_flags(self):
        messages = [_u("add Momentum (Personal)"), _a("Added Momentum"), _u("Notes")]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)


class TestIsErrorRetryWidening:
    def test_simple_retry_of_never_applied_add_is_allowed(self):
        messages = [_u("add Momentum"), _a("AI chat failed", is_error=True), _u("try again")]
        assert find_replayed_actions([_add("Momentum")], messages) == ()

    def test_retry_after_success_and_new_failure_still_flags_earlier_add(self):
        messages = [
            _u("add Momentum"),
            _a("Added Momentum"),
            _u("add Gym"),
            _a("AI chat failed", is_error=True),
            _u("Notes"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)

    def test_failed_turn_mentioning_older_title_does_not_whitelist_it(self):
        messages = [
            _u("add Momentum"),
            _a("Added Momentum"),
            _u("add Gym after Momentum"),
            _a("AI chat failed", is_error=True),
            _u("Notes"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)

    def test_repeat_after_success_then_failure_still_flagged(self):
        messages = [
            _u("add Momentum"),
            _a("Added Momentum"),
            _u("add Momentum"),
            _a("AI chat failed", is_error=True),
            _u("Notes"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)

    def test_chained_failures_excluded_from_prior_text(self):
        messages = [
            _u("add Momentum"),
            _a("AI chat failed", is_error=True),
            _u("try again"),
            _a("AI chat failed", is_error=True),
            _u("try again"),
        ]
        assert find_replayed_actions([_add("Momentum")], messages) == ()

    def test_failure_after_ask_answer_allows_traceable_retry(self):
        messages = [
            _u("add Momentum 09:00-10:00"),
            _a(
                "Momentum does not fit at that time. Please give it a concrete "
                "free start and end time.",
                is_ask=True,
            ),
            _u("14:00"),
            _a("AI chat failed", is_error=True),
            _u("try again"),
        ]
        assert find_replayed_actions([_add("Momentum")], messages) == ()

    def test_sibling_applied_in_ask_triggering_turn_still_flagged(self):
        messages = [
            _u("add Momentum, Gym 09:00"),
            _a(
                "Gym does not fit at that time. Please give it a concrete free "
                "start and end time.",
                is_ask=True,
            ),
            _u("14:00"),
            _a("AI chat failed", is_error=True),
            _u("Notes"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)

    def test_failure_after_ask_answer_does_not_whitelist_older_adds(self):
        messages = [
            _u("add Momentum"),
            _a("Added Momentum"),
            _u("add Gym 09:00"),
            _a(
                "Gym does not fit at that time. Please give it a concrete free "
                "start and end time.",
                is_ask=True,
            ),
            _u("14:00"),
            _a("AI chat failed", is_error=True),
            _u("Notes"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)
        assert find_replayed_actions([_add("Gym")], messages) == ()

    def test_non_contiguous_failures_keep_k_at_contiguous_chain_start(self):
        messages = [
            _u("add Gym"),
            _a("AI chat failed", is_error=True),
            _u("add Momentum"),
            _a("Added Momentum"),
            _u("add TCO"),
            _a("AI chat failed", is_error=True),
            _u("Notes"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)


class TestStopwordOnlyTitles:
    def test_stopword_only_title_falls_back_to_letter_tokens_not_permissive(self):
        messages = [_u("add IT"), _a("Added IT"), _u("Notes")]
        assert find_replayed_actions([_add("IT[2]")], messages) == (0,)

    def test_stopword_only_title_legitimate_case_one(self):
        messages = [
            _u("add Gym"),
            _a("Added Gym"),
            _u("move it later"),
            _a("Moved it"),
            _u("add IT"),
        ]
        assert find_replayed_actions([_add("IT")], messages) == ()

    def test_stopword_only_title_legitimate_case_two(self):
        messages = [_u("add IT"), _a("Added IT"), _u("add IT")]
        assert find_replayed_actions([_add("IT[2]")], messages) == ()

    def test_stopword_only_title_token_fallback_not_whole_title(self):
        messages = [_u("add on call with me"), _a("Added"), _u("Notes")]
        assert find_replayed_actions([_add("Me On")], messages) == (0,)

    def test_stopword_only_title_on_failed_answer_path(self):
        messages = [
            _u("add IT 09:00-10:00"),
            _a(
                "IT does not fit at that time. Please give it a concrete free "
                "start and end time.",
                is_ask=True,
            ),
            _u("14:00"),
            _a("AI chat failed", is_error=True),
            _u("try again"),
        ]
        assert find_replayed_actions([_add("IT")], messages) == ()

    def test_guard_ask_is_never_ask_text_evidence(self):
        messages = [
            _u("add Momentum"),
            _a("Added Momentum"),
            _u("Notes"),
            _a(
                'I did not change the schedule: "Momentum[2]" is not something '
                "you asked for in your last message. What would you like to add?",
                is_ask=True,
            ),
            _u("Notes"),
            _a("AI chat failed", is_error=True),
            _u("try again"),
        ]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)


class TestPrefixTightness:
    def test_short_common_prefix_with_remainder_three_does_not_bridge_step_a(self):
        messages = [_u("add Work"), _a("Added Work"), _u("schedule a workout")]
        assert find_replayed_actions([_add("Work[2]")], messages) == (0,)

    def test_workshop_remainder_four_no_step_a_match(self):
        messages = [_u("add Work"), _a("Added Work"), _u("workshop")]
        assert find_replayed_actions([_add("Work[2]")], messages) == (0,)

    def test_notebook_remainder_four_no_step_a_match(self):
        messages = [_u("add Notes"), _a("Added Notes"), _u("notebook")]
        assert find_replayed_actions([_add("Notes")], messages) == (0,)

    def test_plant_planning_no_match_so_no_step_b_evidence(self):
        messages = [_u("add planning session"), _a("Added"), _u("Обед")]
        assert find_replayed_actions([_add("Plant")], messages) == ()

    def test_cross_language_repeat_with_prior_mention_flagged(self):
        messages = [_u("add Lunch"), _a("Added Lunch"), _u("Обед")]
        assert find_replayed_actions([_add("Lunch[2]")], messages) == (0,)

    def test_short_token_inflection_below_four_chars_is_flagged(self):
        messages = [_u("add gym"), _a("Added gym"), _u("two more gyms")]
        assert find_replayed_actions([_add("Gym[2]")], messages) == (0,)

    def test_stopwords_excluded_from_token_match(self):
        messages = [_u("Plan for Friday"), _a("Added"), _u("add notes for later")]
        assert find_replayed_actions([_add("Plan for Friday[2]")], messages) == (0,)


class TestInflectionAllowed:
    def test_english_plural_inflection_allowed(self):
        messages = [_u("add meeting"), _a("Added meeting"), _u("two more meetings")]
        assert find_replayed_actions([_add("Meeting[2]")], messages) == ()

    def test_russian_case_inflection_allowed(self):
        messages = [_u("добавь обед"), _a("Added"), _u("ещё обеда")]
        assert find_replayed_actions([_add("Обед[2]")], messages) == ()

    def test_unrelated_words_no_prefix_match_flagged(self):
        messages = [_u("add Momentum"), _a("Added Momentum"), _u("Notes")]
        assert find_replayed_actions([_add("Momentum[2]")], messages) == (0,)


class TestOnlyRealAskDisablesGuard:
    def test_question_shaped_explanation_without_is_ask_still_enforced(self):
        messages = [_u("add Gym"), _a("Shall I add Gym?"), _u("yes")]
        assert find_replayed_actions([_add("Gym")], messages) == (0,)


class TestScope:
    def test_non_add_actions_never_returned(self):
        messages = [_u("add Momentum"), _a("Added Momentum"), _u("remove it")]
        actions = [{"type": "remove", "task_id": 1}]
        assert find_replayed_actions(actions, messages) == ()

    def test_returns_all_offending_indices_for_multi_add(self):
        messages = [_u("add Momentum"), _a("Added Momentum"), _u("Notes")]
        actions = [_add("Momentum[2]"), _add("Momentum[3]"), _add("Notes")]
        assert find_replayed_actions(actions, messages) == (0, 1)
