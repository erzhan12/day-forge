"""Relative-add guard cases that must not reach ordinary auto-placement."""

import datetime
from types import SimpleNamespace

import pytest
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
    ) == "Во сколько начать новый блок после блока «Зал»?"


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
    ) == "Во сколько начать новый блок после блока «Зал»?"


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


def test_concrete_answer_resolves_procedural_before_without_block_anchor():
    messages = [
        _user("Add Vocal for 30 minutes. Ask for its start time before adding it."),
        {"role": "assistant", "content": "What start time?", "is_ask": True},
        _user("14:00"),
    ]
    assert relative_add_guard_ask(
        messages, [_add(start_time="14:00", end_time="14:30")], []
    ) is None


def test_concrete_answer_cannot_override_existing_relative_anchor():
    messages = [
        _user("Add Vocal after Gym"),
        {"role": "assistant", "content": "What start time?", "is_ask": True},
        _user("08:00"),
    ]
    assert relative_add_guard_ask(
        messages, [_add(start_time="08:00", end_time="08:30")], [_block()]
    ) == "What start time should the new block have after Gym?"


@pytest.mark.parametrize("answer,action", [
    ("30 minutes", _add(start_time="14:00", end_time="14:30")),
    ("14:00", _add(duration_minutes=30)),
])
def test_unbound_relation_still_rejects_non_clock_or_untimed_answers(answer, action):
    messages = [
        _user("Add Vocal after Lunch"),
        {"role": "assistant", "content": "What time?", "is_ask": True},
        _user(answer),
    ]
    assert relative_add_guard_ask(messages, [action], []) is not None


@pytest.mark.parametrize("opening,closing", [('"', '"'), ("'", "'"), ("“", "”"), ("«", "»")])
@pytest.mark.parametrize("start,expected", [
    ("08:00", "What start time should the new block have after Gym?"), ("10:00", None),
])
def test_quoted_action_title_is_not_a_placement_relation(opening, closing, start, expected):
    title = "Walk after lunch"
    command = f"Add {opening}{title}{closing} after Gym"
    messages = [
        _user(command),
        {"role": "assistant", "content": "What time?", "is_ask": True},
        _user(start),
    ]
    action = {**_add(start_time=start, end_time=start[:3] + "30"), "title": title}
    assert relative_add_guard_ask(messages, [action], [_block()]) == expected


def test_quoted_title_without_relative_placement_is_an_ordinary_add():
    action = {**_add(start_time="10:00", end_time="10:30"), "title": "Walk after lunch"}
    assert relative_add_guard_ask([_user('Add "Walk after lunch" at 10:00')], [action], []) is None


@pytest.mark.parametrize("start", ["08:00", "10:00"])
def test_quoted_anchor_title_keeps_its_external_relation(start):
    anchor = "Focus before lunch"
    ask = relative_add_guard_ask(
        [_user(f'Add Vocal after "{anchor}"')],
        [_add(start_time=start, end_time=start[:3] + "30")],
        [_block(title=anchor)],
    )
    expected = (
        f"What start time should the new block have after {anchor}?" if start == "08:00" else None
    )
    assert ask == expected


def test_quoting_a_whole_command_does_not_hide_its_relative_constraint():
    assert relative_add_guard_ask(
        [_user('"Add Vocal after Gym"')],
        [_add(start_time="08:00", end_time="08:30")],
        [_block()],
    ) == "What start time should the new block have after Gym?"


def _screenshot_chat(answer):
    return [
        _user("разбор по антихрупкости после прогулки"),
        {
            "role": "assistant",
            "content": "После какого блока поставить новый?",
            "is_ask": True,
        },
        _user(answer),
    ]


_DAY = [
    _block(title="Kick-off", start="12:40", end="13:05"),
    _block(title="Lunch Walk", start="15:00", end="16:00"),
]


def test_answer_naming_a_block_resolves_unknown_anchor():
    """Regression: the answer to "which block?" was ignored, so the same
    question repeated forever."""
    assert relative_add_guard_ask(
        _screenshot_chat("Lunch Walk"), [_add()], _DAY
    ) == "Во сколько начать новый блок после блока «Lunch Walk»?"


def test_answer_anchor_accepts_a_timed_add_after_it():
    assert relative_add_guard_ask(
        _screenshot_chat("Lunch Walk"),
        [_add(start_time="16:00", end_time="16:30")],
        _DAY,
    ) is None


def test_answer_anchor_still_rejects_a_timed_add_before_it():
    assert relative_add_guard_ask(
        _screenshot_chat("lunch walk"),
        [_add(start_time="14:00", end_time="14:30")],
        _DAY,
    ) == "Во сколько начать новый блок после блока «Lunch Walk»?"


def test_answer_naming_no_block_keeps_asking_which_block():
    assert relative_add_guard_ask(
        _screenshot_chat("прогулка"), [_add()], _DAY
    ) == "После какого блока поставить новый?"


def test_answer_disambiguates_between_named_anchors():
    blocks = [_block(title="Gym"), _block(title="Gym Stretch", start="10:00", end="10:30")]
    messages = [
        _user("add Vocal after Gym Stretch or Gym"),
        {"role": "assistant", "content": "Which one?", "is_ask": True},
        _user("Gym Stretch"),
    ]
    assert relative_add_guard_ask(messages, [_add()], blocks) == (
        "What start time should the new block have after Gym Stretch?"
    )


@pytest.mark.parametrize("request_text,expected", [
    ("добавь Вокал после Обеда", "После какого блока поставить новый?"),
    ("добавь Вокал перед Обедом", "Перед каким блоком поставить новый?"),
    ("добавь Вокал после Зала и после Обеда", "Во сколько начать новый блок?"),
])
def test_russian_requests_get_russian_questions(request_text, expected):
    assert relative_add_guard_ask([_user(request_text)], [_add()], [_block()]) == expected


def test_russian_before_question_names_the_anchor():
    assert relative_add_guard_ask(
        [_user("добавь Вокал до Зала")],
        [_add(start_time="09:10", end_time="09:35")],
        [_block(title="Зал")],
    ) == "Во сколько начать новый блок перед блоком «Зал»?"


def test_anchor_named_in_an_earlier_reply_still_constrains_a_clock_answer():
    messages = _screenshot_chat("Lunch Walk") + [
        {
            "role": "assistant",
            "content": "Во сколько начать новый блок после блока «Lunch Walk»?",
            "is_ask": True,
        },
        _user("14:00"),
    ]
    assert relative_add_guard_ask(
        messages, [_add(start_time="14:00", end_time="14:30")], _DAY
    ) == "Во сколько начать новый блок после блока «Lunch Walk»?"
    assert relative_add_guard_ask(
        messages, [_add(start_time="16:00", end_time="16:30")], _DAY
    ) is None


def test_correction_naming_two_blocks_does_not_fall_back_to_older_answer():
    messages = _screenshot_chat("Lunch Walk") + [
        {
            "role": "assistant",
            "content": "Во сколько начать новый блок после блока «Lunch Walk»?",
            "is_ask": True,
        },
        _user("нет, не Lunch Walk, а Kick-off"),
    ]
    assert relative_add_guard_ask(
        messages, [_add(start_time="14:00", end_time="14:30")], _DAY
    ) == "После какого блока поставить новый?"


def _ask(content="Во сколько?"):
    return {"role": "assistant", "content": content, "is_ask": True}


def test_reply_naming_two_blocks_still_constrains_a_later_clock_answer():
    messages = _screenshot_chat("Kick-off или Lunch Walk") + [_ask(), _user("14:00")]
    assert relative_add_guard_ask(
        messages, [_add(start_time="14:00", end_time="14:30")], _DAY
    ) == "После какого блока поставить новый?"


def test_ambiguous_correction_followed_by_clock_answer_keeps_asking():
    messages = _screenshot_chat("Lunch Walk") + [
        _ask(),
        _user("нет, не Lunch Walk, а Kick-off"),
        _ask(),
        _user("11:00"),
    ]
    assert relative_add_guard_ask(
        messages, [_add(start_time="11:00", end_time="11:30")], _DAY
    ) == "После какого блока поставить новый?"


def test_newest_reply_overrides_an_earlier_answer():
    messages = [
        _user("add Vocal after Kick-off or Lunch Walk"),
        _ask("Which one?"),
        _user("Kick-off"),
        _ask("What time?"),
        _user("actually Lunch Walk"),
    ]
    assert relative_add_guard_ask(messages, [_add()], _DAY) == (
        "What start time should the new block have after Lunch Walk?"
    )


def test_english_request_with_russian_reply_gets_russian_question():
    messages = [
        _user("add Vocal after Lunch"),
        _ask("Which existing block should the new block be placed after?"),
        _user("прогулка"),
    ]
    assert relative_add_guard_ask(messages, [_add()], _DAY) == (
        "После какого блока поставить новый?"
    )


def test_reply_that_is_a_title_with_a_command_word_resolves_the_anchor():
    blocks = _DAY + [_block(title="Schedule planning", start="15:30", end="16:00")]
    messages = _screenshot_chat("Schedule planning")
    assert relative_add_guard_ask(
        messages, [_add(start_time="08:00", end_time="08:30")], blocks
    ) == "Во сколько начать новый блок после блока «Schedule planning»?"


@pytest.mark.parametrize("answer", ['"Gym Stretch"', "«Gym Stretch»"])
def test_quoted_reply_picks_the_exact_title(answer):
    blocks = [_block(title="Gym"), _block(title="Gym Stretch", start="10:00", end="10:30")]
    messages = [
        _user("add Vocal after the workout"),
        _ask("Which one?"),
        _user(answer),
    ]
    assert relative_add_guard_ask(messages, [_add()], blocks) == (
        "What start time should the new block have after Gym Stretch?"
    )


def test_reply_can_pick_a_block_outside_the_requested_candidates():
    blocks = _DAY + [_block(title="Reading", start="17:00", end="17:30")]
    messages = [
        _user("add Vocal after Kick-off or Lunch Walk"),
        _ask("Which one?"),
        _user("Reading"),
    ]
    assert relative_add_guard_ask(messages, [_add()], blocks) == (
        "What start time should the new block have after Reading?"
    )


def test_clock_target_ignores_a_reply_that_names_a_block():
    messages = [
        _user("add Vocal before 10:00"),
        _ask("How long?"),
        _user("30 minutes, like Gym"),
    ]
    assert relative_add_guard_ask(
        messages, [_add(start_time="09:00", end_time="09:30")], [_block()]
    ) is None


def test_title_only_retry_after_error_keeps_the_relative_request():
    messages = [
        _user("add Vocal after Lunch Walk"),
        {"role": "assistant", "content": "Network error", "is_error": True},
        _user("Lunch Walk"),
    ]
    assert relative_add_guard_ask(
        messages, [_add(start_time="14:00", end_time="14:30")], _DAY
    ) == "What start time should the new block have after Lunch Walk?"


def test_reply_naming_a_command_word_title_and_another_block_keeps_asking():
    blocks = _DAY + [_block(title="Schedule planning", start="15:30", end="16:00")]
    messages = _screenshot_chat("Schedule planning или Lunch Walk")
    assert relative_add_guard_ask(messages, [_add()], blocks) == (
        "После какого блока поставить новый?"
    )
    later = messages + [_ask(), _user("08:00")]
    assert relative_add_guard_ask(
        later, [_add(start_time="08:00", end_time="08:30")], blocks
    ) == "После какого блока поставить новый?"
