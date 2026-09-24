"""Unit tests for ``ai.implicit_add`` (feature 0083, Addendum D).

Pure module — stdlib only, no Django, no DB. See
``docs/features/0083_PLAN.md`` § "Addendum D — Implicit 'add' for
command-less turns" for the rationale and the exact exclusion list this
pins.
"""

from ai.implicit_add import apply_implicit_add


def _u(text, **flags):
    return {"role": "user", "content": text, **flags}


def _a(text, **flags):
    return {"role": "assistant", "content": text, **flags}


class TestPrefixed:
    """Command-less turns get the add verb prepended."""

    def test_bare_title_gets_add_prefix(self):
        messages = [_u("Notes")]
        assert apply_implicit_add("Notes", messages) == "add Notes"

    def test_cyrillic_bare_title_gets_dobavi_prefix(self):
        messages = [_u("Обед")]
        assert apply_implicit_add("Обед", messages) == "добавь Обед"

    def test_longer_command_less_phrase_gets_add_prefix(self):
        text = "Reading emails 30 min"
        messages = [_u(text)]
        assert apply_implicit_add(text, messages) == f"add {text}"


class TestUnchangedExplicitVerb:
    """A turn that already carries an explicit command verb is untouched."""

    def test_english_verb_present(self):
        text = "move Gym to 18:00"
        messages = [_u(text)]
        assert apply_implicit_add(text, messages) == text

    def test_russian_stem_present(self):
        text = "удали Momentum"
        messages = [_u(text)]
        assert apply_implicit_add(text, messages) == text

    def test_inflected_verb_present(self):
        text = "Moved"
        messages = [_u(text)]
        assert apply_implicit_add(text, messages) == text

    def test_verb_as_first_word(self):
        text = "schedule a workout"
        messages = [_u(text)]
        assert apply_implicit_add(text, messages) == text


class TestUnchangedQuestion:
    def test_question_mark(self):
        text = "what's next?"
        messages = [_u(text)]
        assert apply_implicit_add(text, messages) == text

    def test_russian_question_starter(self):
        text = "когда обед"
        messages = [_u(text)]
        assert apply_implicit_add(text, messages) == text


class TestUnchangedShortReply:
    def test_thanks(self):
        messages = [_u("thanks")]
        assert apply_implicit_add("thanks", messages) == "thanks"

    def test_russian_da(self):
        messages = [_u("да")]
        assert apply_implicit_add("да", messages) == "да"


class TestUnchangedEmpty:
    def test_empty_string(self):
        messages = [_u("")]
        assert apply_implicit_add("", messages) == ""

    def test_whitespace_only(self):
        messages = [_u("   ")]
        assert apply_implicit_add("   ", messages) == "   "


class TestUnchangedPendingAsk:
    def test_pending_ask_answer_left_alone(self):
        messages = [
            _u("add Gym"),
            _a("What time?", is_ask=True),
            _u("later"),
        ]
        assert apply_implicit_add("later", messages) == "later"

    def test_pending_ask_answer_with_bare_title(self):
        messages = [
            _u("some earlier turn"),
            _a("Add what?", is_ask=True),
            _u("Gym"),
        ]
        assert apply_implicit_add("Gym", messages) == "Gym"

    def test_non_ask_previous_assistant_turn_still_prefixed(self):
        # Previous assistant turn exists but is NOT a pending ask -> the
        # command-less exclusion does not apply.
        messages = [
            _u("add Gym"),
            _a("Added Gym", is_ask=False),
            _u("Notes"),
        ]
        assert apply_implicit_add("Notes", messages) == "add Notes"


class TestUnchangedAfterErrorBubble:
    """A retry after a failure bubble continues the failed request (rule 11(b))."""

    def test_try_again_after_error_left_alone(self):
        messages = [
            _u("add Momentum"),
            _a("AI chat failed", is_error=True),
            _u("try again"),
        ]
        assert apply_implicit_add("try again", messages) == "try again"

    def test_bare_title_after_error_left_alone(self):
        messages = [
            _u("add Momentum"),
            _a("AI chat failed", is_error=True),
            _u("Momentum"),
        ]
        assert apply_implicit_add("Momentum", messages) == "Momentum"

    def test_retry_words_without_error_flag_left_alone(self):
        for text in ("retry", "try again", "ещё раз", "повтори"):
            assert apply_implicit_add(text, [_u(text)]) == text


class TestUnchangedChitChatVariants:
    """Punctuation, apostrophes and greetings do not defeat the exclusions."""

    def test_short_reply_with_punctuation(self):
        for text in ("thanks!", "Ok.", "Спасибо!", "  yes!!  "):
            assert apply_implicit_add(text, [_u(text)]) == text

    def test_question_starter_with_apostrophe_and_no_question_mark(self):
        for text in ("What's next", "How's my day looking"):
            assert apply_implicit_add(text, [_u(text)]) == text

    def test_greetings(self):
        for text in ("Good morning", "good night!", "Доброе утро", "bye"):
            assert apply_implicit_add(text, [_u(text)]) == text


class TestUnchangedIrregularVerbForms:
    """Doubled-consonant, y->ied and British spellings still count as commands."""

    def test_irregular_english_forms(self):
        for text in (
            "putting Gym at 9",
            "setting lunch to 13:00",
            "splitting the work block",
            "swapping Gym and Lunch",
            "tried again",
            "cancelled standup",
            "made it longer",
        ):
            assert apply_implicit_add(text, [_u(text)]) == text


class TestUnchangedPlanningCommands:
    """Edit/planning verbs and the chat suggestion chips are never prefixed."""

    def test_reschedule_postpone_and_friends(self):
        for text in (
            "reschedule Gym for 18:00",
            "postpone Gym until 18:00",
            "push lunch by 30 min",
            "free up the afternoon",
            "отложи обед на час",
            "спланируй вечер",
        ):
            assert apply_implicit_add(text, [_u(text)]) == text

    def test_suggestion_chips_left_alone(self):
        # frontend/src/utils/chatSuggestions.ts — one-click prompts must
        # reach the model verbatim, never as "add Plan my remaining day".
        for text in (
            "Plan my remaining day",
            "Add a focused work block",
            "Make room for a break",
        ):
            assert apply_implicit_add(text, [_u(text)]) == text


class TestReadOnlyRequests:
    """Read-only requests are never turned into adds; common titles still are."""

    def test_read_only_imperatives_left_alone(self):
        for text in (
            "list today's blocks",
            "show my afternoon",
            "tell me what's left",
            "покажи мои блоки",
            "расскажи про вечер",
        ):
            assert apply_implicit_add(text, [_u(text)]) == text

    def test_check_and_review_titles_still_prefixed(self):
        for text in ("Check emails", "Review PR"):
            assert apply_implicit_add(text, [_u(text)]) == f"add {text}"
