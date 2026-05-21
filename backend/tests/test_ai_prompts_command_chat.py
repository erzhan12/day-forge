"""Unit tests for the command + chat prompt builders (feature 0012).

Pure-function tests against ``build_user_message`` and
``build_chat_user_message``. The prompt builders now render an
``Active rules (priority desc):`` section so the model can fill omitted
defaults from rules instead of asking for clarification.

Active/user-owned filtering is the view layer's responsibility (see
``ai.views._load_active_rules``); the builders render whatever rules
they are handed, in iteration order. These tests pin both invariants
so a refactor that moves filtering into the prompt layer (or drops the
section entirely) fails here.
"""
import datetime
from types import SimpleNamespace

from ai.prompts import (
    CHAT_TRANSCRIPT_HEADER,
    _format_rules_section,
    build_chat_user_message,
    build_user_message,
)


def _rule(text: str):
    """Minimal duck-typed rule: only ``.text`` is read by the formatter."""
    return SimpleNamespace(text=text)


def _schedule(date_):
    return SimpleNamespace(date=date_)


class TestFormatRulesSection:
    def test_empty_iterable_renders_no_active_rules(self):
        section = _format_rules_section([])
        assert section == "Active rules (priority desc):\n(no active rules)"

    def test_rules_render_in_passed_order(self):
        section = _format_rules_section([_rule("first"), _rule("second")])
        # 1. + JSON-encoded text
        assert '1. "first"' in section
        assert '2. "second"' in section
        # Ordering preserved as passed in (caller orders by -priority).
        assert section.index("first") < section.index("second")

    def test_rule_text_is_json_encoded_with_unicode_preserved(self):
        # Embedded quote must be escaped so it can't reshape the prompt;
        # Cyrillic must survive untouched (ensure_ascii=False).
        section = _format_rules_section([_rule('he said "go"')])
        assert '\\"go\\"' in section
        section_ru = _format_rules_section([_rule("Тренировка 25 мин")])
        assert "Тренировка 25 мин" in section_ru


class TestBuildUserMessage:
    def test_includes_active_rules_section(self):
        schedule = _schedule(datetime.date(2026, 5, 4))
        now = datetime.datetime(2026, 5, 4, 9, 30)
        msg = build_user_message(
            schedule, [], now, "add standup", [_rule("25 min blocks by default")]
        )
        assert "Active rules (priority desc):" in msg
        assert "25 min blocks by default" in msg

    def test_multiple_rules_render_in_priority_order(self):
        """The caller passes rules already ordered by ``-priority``; the
        builder must preserve that order verbatim."""
        schedule = _schedule(datetime.date(2026, 5, 4))
        now = datetime.datetime(2026, 5, 4, 9, 30)
        rules = [
            _rule("HIGH priority rule"),
            _rule("MID priority rule"),
            _rule("LOW priority rule"),
        ]
        msg = build_user_message(schedule, [], now, "do stuff", rules)
        assert (
            msg.index("HIGH priority rule")
            < msg.index("MID priority rule")
            < msg.index("LOW priority rule")
        )

    def test_user_command_section_follows_rules_section(self):
        """The model sees rules-as-defaults BEFORE the user command, so
        defaults are in scope when the command is interpreted. Locks the
        section order so a future refactor cannot silently flip it."""
        schedule = _schedule(datetime.date(2026, 5, 4))
        now = datetime.datetime(2026, 5, 4, 9, 30)
        msg = build_user_message(
            schedule, [], now, "add standup", [_rule("R1")]
        )
        assert "Active rules (priority desc):" in msg
        assert "User command:" in msg
        assert msg.index("Active rules") < msg.index("User command:")
        # JSON-encoded command still present after the rules section.
        assert '"add standup"' in msg
        assert msg.index('"add standup"') > msg.index("Active rules")

    def test_empty_rules_renders_no_active_rules_placeholder(self):
        schedule = _schedule(datetime.date(2026, 5, 4))
        now = datetime.datetime(2026, 5, 4, 9, 30)
        msg = build_user_message(schedule, [], now, "hi", [])
        assert "Active rules (priority desc):\n(no active rules)" in msg


class TestBuildChatUserMessage:
    def test_includes_active_rules_section(self):
        schedule = _schedule(datetime.date(2026, 5, 4))
        now = datetime.datetime(2026, 5, 4, 9, 30)
        msg = build_chat_user_message(
            schedule, [], now, [_rule("10 min gap between blocks")]
        )
        assert "Active rules (priority desc):" in msg
        assert "10 min gap between blocks" in msg

    def test_rule_present_in_schedule_context_not_transcript(self):
        """Rules live in the trusted schedule-context message that
        ``run_chat`` sends BEFORE the untrusted transcript flatten.
        They must not be smuggled into the prior-transcript section."""
        schedule = _schedule(datetime.date(2026, 5, 4))
        now = datetime.datetime(2026, 5, 4, 9, 30)
        msg = build_chat_user_message(
            schedule, [], now, [_rule("RULE-IN-CONTEXT")]
        )
        assert "RULE-IN-CONTEXT" in msg
        # build_chat_user_message must NOT itself render the
        # transcript header — that belongs to serialise_prior_turns.
        assert CHAT_TRANSCRIPT_HEADER not in msg

    def test_empty_rules_renders_placeholder(self):
        schedule = _schedule(datetime.date(2026, 5, 4))
        now = datetime.datetime(2026, 5, 4, 9, 30)
        msg = build_chat_user_message(schedule, [], now, [])
        assert "Active rules (priority desc):\n(no active rules)" in msg

    def test_blocks_section_precedes_rules_section(self):
        """Section order: schedule date → current time → existing blocks
        → active rules. Locked so refactors don't silently shuffle it."""
        schedule = _schedule(datetime.date(2026, 5, 4))
        now = datetime.datetime(2026, 5, 4, 9, 30)
        msg = build_chat_user_message(
            schedule, [], now, [_rule("R")]
        )
        assert msg.index("Existing blocks:") < msg.index("Active rules")
