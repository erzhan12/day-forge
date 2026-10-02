"""Relative-add guard cases that must not reach ordinary auto-placement."""

import datetime
from types import SimpleNamespace

from ai.relative_add_guard import relative_add_guard_ask


def _block(title="Gym", start="09:00", end="09:30"):
    return SimpleNamespace(
        title=title,
        start_time=datetime.time.fromisoformat(start),
        end_time=datetime.time.fromisoformat(end),
    )


def _user(content):
    return {"role": "user", "content": content}


def _add(**times):
    return {"type": "add", "title": "Vocal", "category": "other", **times}


def test_untimed_after_existing_block_requires_concrete_time():
    ask = relative_add_guard_ask(
        [_user("add Vocal for 25 minutes after Gym with a 10-minute gap")],
        [_add(duration_minutes=25)],
        [_block()],
    )
    assert ask == "What start time should the new block have after Gym?"


def test_explicit_add_before_anchor_is_rejected():
    ask = relative_add_guard_ask(
        [_user("add Vocal after Gym")],
        [_add(start_time="08:00", end_time="08:25")],
        [_block()],
    )
    assert ask == "What start time should the new block have after Gym?"


def test_explicit_add_after_anchor_is_allowed():
    assert (
        relative_add_guard_ask(
            [_user("add Vocal after Gym")],
            [_add(start_time="09:40", end_time="10:05")],
            [_block()],
        )
        is None
    )


def test_multi_add_checks_relative_target_without_blocking_untimed_sibling():
    assert relative_add_guard_ask(
        [_user("add Vocal after Gym and also add Notes")],
        [
            _add(start_time="09:40", end_time="10:05"),
            {"type": "add", "title": "Notes", "category": "other"},
        ],
        [_block()],
    ) is None


def test_seconds_in_explicit_time_do_not_crash_guard():
    assert relative_add_guard_ask(
        [_user("add Vocal after Gym")],
        [_add(start_time="09:40:00", end_time="10:05:00")],
        [_block()],
    ) is None


def test_explicit_add_must_keep_requested_gap():
    assert relative_add_guard_ask(
        [_user("add Vocal after Gym with a 10-minute gap")],
        [_add(start_time="09:35", end_time="10:00")],
        [_block()],
    ) == "What start time should the new block have after Gym?"


def test_explicit_add_must_keep_russian_requested_gap():
    assert relative_add_guard_ask(
        [_user("добавь Вокал после Зала с отступом 10 минут")],
        [_add(start_time="09:35", end_time="10:00")],
        [_block(title="Зал")],
    ) == "What start time should the new block have after Зал?"


def test_explicit_add_must_keep_gap_in_mins_form():
    assert relative_add_guard_ask(
        [_user("add Vocal after Gym with a 10 mins gap")],
        [_add(start_time="09:35", end_time="10:00")],
        [_block()],
    ) == "What start time should the new block have after Gym?"


def test_before_relation_checks_end_time():
    assert relative_add_guard_ask(
        [_user("add Vocal before Gym")],
        [_add(start_time="09:10", end_time="09:35")],
        [_block()],
    ) == "What start time should the new block have before Gym?"


def test_pending_reply_preserves_relative_request():
    messages = [
        _user("add Vocal after Gym"),
        {"role": "assistant", "content": "Past or now?", "is_ask": True},
        _user("past"),
    ]
    assert relative_add_guard_ask(messages, [_add()], [_block()]) is not None


def test_relative_answer_to_pending_add_is_guarded():
    messages = [
        _user("add Vocal"),
        {"role": "assistant", "content": "When should Vocal start?", "is_ask": True},
        _user("after Gym"),
    ]
    assert relative_add_guard_ask(messages, [_add()], [_block()]) == (
        "What start time should the new block have after Gym?"
    )


def test_retry_after_error_preserves_relative_request():
    messages = [
        _user("add Vocal after Gym"),
        {"role": "assistant", "content": "Network error", "is_error": True},
        _user("try again"),
    ]
    assert relative_add_guard_ask(messages, [_add()], [_block()]) is not None


def test_fresh_add_supersedes_pending_relative_request():
    messages = [
        _user("add Vocal after Gym"),
        {"role": "assistant", "content": "What time?", "is_ask": True},
        _user("add Notes"),
    ]
    assert relative_add_guard_ask(messages, [_add()], [_block()]) is None


def test_russian_relative_request_is_guarded():
    assert relative_add_guard_ask(
        [_user("добавь Вокал после Зала")],
        [_add()],
        [_block(title="Зал")],
    ) == "What start time should the new block have after Зал?"


def test_ordinary_untimed_add_is_unchanged():
    assert relative_add_guard_ask([_user("add Vocal")], [_add()], [_block()]) is None


def test_commandless_relative_add_is_guarded():
    assert relative_add_guard_ask(
        [_user("Vocal after Gym")], [_add()], [_block()]
    ) == "What start time should the new block have after Gym?"


def test_title_starting_with_after_is_not_a_relation():
    assert relative_add_guard_ask([_user("add After Hours")], [_add()], [_block()]) is None


def test_title_starting_with_after_can_still_have_a_relation():
    assert relative_add_guard_ask(
        [_user("add After Hours after Gym")], [_add()], [_block()]
    ) == "What start time should the new block have after Gym?"


def test_unknown_reference_asks_which_block():
    assert relative_add_guard_ask(
        [_user("add Vocal after Lunch")], [_add()], [_block()]
    ) == "Which existing block should the new block be placed after?"


def test_clock_reference_is_not_treated_as_a_block():
    assert relative_add_guard_ask(
        [_user("add Vocal before 10:00")],
        [_add(start_time="09:00", end_time="09:25")],
        [_block()],
    ) is None
