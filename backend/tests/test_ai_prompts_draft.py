"""Unit tests for the draft prompt builders.

Pure-function tests; no Django ORM unless required for ``time_blocks``
prefetch. ``build_draft_user_message`` is the load-bearing piece for
draft accuracy: any regression in section ordering, history filtering, or
rules formatting will silently degrade draft quality, so each is asserted.
"""
import datetime

import pytest
from ai.prompts import (
    SYSTEM_PROMPT_DRAFT,
    _format_block_line,
    _format_rules_section,
    _runtime_block_to_dict,
    _template_entry_to_dict,
    build_draft_user_message,
    build_system_prompt_chat,
    build_system_prompt_draft,
)
from analytics.models import DailyReview
from schedules.models import Schedule, TimeBlock
from schedules.window import DEFAULT_WINDOW, ScheduleWindow
from templates_mgr.models import Rule, Template


def test_system_prompt_only_allows_add():
    assert "add" in SYSTEM_PROMPT_DRAFT
    assert "No move/remove/resize" in SYSTEM_PROMPT_DRAFT


def test_build_system_prompt_draft_embeds_custom_window_bounds():
    """The rendered draft system prompt must reflect the user's actual window,
    not the hardcoded 06:00-23:00 default (feature 0053)."""
    window = ScheduleWindow(datetime.time(8, 0), datetime.time(21, 0))
    prompt = build_system_prompt_draft(window)
    assert "08:00-21:00" in prompt
    # The default bounds must NOT leak into a narrowed-window prompt.
    assert "06:00-23:00" not in prompt


def test_build_system_prompt_chat_embeds_custom_window_bounds():
    window = ScheduleWindow(datetime.time(8, 0), datetime.time(21, 0))
    prompt = build_system_prompt_chat(window)
    assert "08:00-21:00" in prompt
    assert "06:00-23:00" not in prompt


def test_build_system_prompt_draft_default_window_bounds():
    """The default window still renders the historical 06:00-23:00 bounds."""
    prompt = build_system_prompt_draft(DEFAULT_WINDOW)
    assert "06:00-23:00" in prompt


@pytest.mark.django_db
def test_format_block_line_runtime_block(user):
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 5, 1))
    block = TimeBlock.objects.create(
        schedule=schedule,
        title="Standup",
        start_time=datetime.time(10, 0),
        end_time=datetime.time(10, 15),
        category="work",
        is_completed=True,
    )
    line = _format_block_line(_runtime_block_to_dict(block))
    assert f"id={block.id}" in line
    assert "10:00-10:15" in line
    assert "work" in line
    assert "completed=true" in line
    assert "Standup" in line


def test_format_block_line_template_entry():
    entry = {
        "title": "Lunch",
        "start_time": "12:00",
        "end_time": "13:00",
        "category": "other",
    }
    line = _format_block_line(_template_entry_to_dict(entry, synthetic_id=-1))
    assert "id=-1" in line
    assert "12:00-13:00" in line
    assert "completed=false" in line
    assert "Lunch" in line


@pytest.mark.django_db
def test_build_draft_user_message_full_context(user):
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)  # Monday
    )
    template = Template.objects.create(
        user=user,
        name="WD",
        type="weekday",
        blocks=[
            {
                "title": "Deep work",
                "start_time": "09:00",
                "end_time": "12:00",
                "category": "work",
            },
        ],
    )

    # History: yesterday active + the day before draft (excluded).
    yesterday = Schedule.objects.create(
        user=user,
        date=datetime.date(2026, 5, 3),
        status=Schedule.Status.ACTIVE,
    )
    TimeBlock.objects.create(
        schedule=yesterday,
        title="Sunday gym",
        start_time=datetime.time(10, 0),
        end_time=datetime.time(11, 0),
        category="health",
    )
    older_draft = Schedule.objects.create(
        user=user,
        date=datetime.date(2026, 5, 2),
        status=Schedule.Status.DRAFT,
    )
    TimeBlock.objects.create(
        schedule=older_draft,
        title="Should be hidden",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        category="other",
    )

    Rule.objects.create(
        user=user, text="No meetings before 9", priority=10, is_active=True
    )
    Rule.objects.create(
        user=user, text="Lunch 12-13", priority=5, is_active=True
    )

    rules = list(
        Rule.objects.filter(user=user, is_active=True).order_by("-priority")
    )
    history = list(
        Schedule.objects.filter(user=user)
        .exclude(pk=schedule.pk)
        .order_by("date")
        .prefetch_related("time_blocks")
    )

    now = datetime.datetime(2026, 5, 4, 7, 30)
    msg = build_draft_user_message(schedule, template, history, rules, now)

    assert "Schedule date: 2026-05-04 (Monday)" in msg
    assert "Current local time: 07:30" in msg
    assert "Active template (weekday):" in msg
    assert "Deep work" in msg
    assert "Active rules (priority desc):" in msg
    # Priority order: high then low
    assert msg.index("No meetings before 9") < msg.index("Lunch 12-13")
    # User command section is absent
    assert "User command:" not in msg
    # Yesterday (active) is included; the older draft is filtered out.
    assert "Sunday gym" in msg
    assert "Should be hidden" not in msg


def _squash(text: str) -> str:
    """Collapse every whitespace run (newlines included) to a single space.

    The draft system prompt is hard-wrapped at ~72 columns with 3-space
    continuation indents, so a multi-word phrase is not a contiguous
    substring of the raw text. Normalising before a substring assertion
    keeps these tests pinned to prompt *wording* rather than to the
    incidental line breaks, which a re-wrap would otherwise break.
    """
    return " ".join(text.split())


@pytest.mark.django_db
def test_draft_user_message_renders_current_local_date_not_schedule_date(user):
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 5, 5))

    msg = build_draft_user_message(
        schedule, None, [], [], datetime.datetime(2026, 5, 4, 12, 0)
    )

    current_local_time_line = next(
        line for line in msg.splitlines() if line.startswith("Current local time:")
    )
    assert (
        current_local_time_line
        == "Current local time: 12:00 on 2026-05-04 (context only — not a cutoff)"
    )
    assert "2026-05-05" not in current_local_time_line


@pytest.mark.django_db
def test_draft_prompt_keeps_past_template_block_at_noon(user):
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 5, 4))
    template = Template.objects.create(
        user=user,
        name="WD",
        type="weekday",
        blocks=[
            {
                "title": "Gym",
                "start_time": "07:30",
                "end_time": "08:30",
                "category": "health",
            }
        ],
    )

    msg = build_draft_user_message(
        schedule, template, [], [], datetime.datetime(2026, 5, 4, 12, 0)
    )

    assert 'id=-1 07:30-08:30 health completed=false title="Gym"' in msg
    prompt = _squash(build_system_prompt_draft(DEFAULT_WINDOW))
    assert "never a reason to leave a block out" in prompt
    assert "Past blocks must stay in the draft" in prompt


def test_draft_prompt_past_keep_overrides_history_skip_permission():
    prompt = build_system_prompt_draft(DEFAULT_WINDOW)
    # Slice the RAW prompt on the line-start rule markers so the test still
    # pins rule *locality*; normalise only afterwards, for the wrapping.
    rule_two = _squash(prompt.split("\n2. ", 1)[1].split("\n3. ", 1)[0])

    assert "consistently shifted" in rule_two
    assert "routinely skipped" in rule_two
    assert "overrides the permission above to drop routinely skipped blocks" in rule_two
    assert "active user rule" in rule_two
    assert "takes precedence" in rule_two
    assert "Working day window" in _squash(prompt)
    assert "must not overlap" in _squash(prompt)


def test_draft_prompt_scopes_past_rule_and_forbids_moving_past_blocks():
    prompt = _squash(build_system_prompt_draft(DEFAULT_WINDOW))

    assert "schedule date is today" in prompt
    assert "schedule date is already past" in prompt
    # "Past" must be keyed on the block's START time, not its end time: an
    # end_time-based rule would still satisfy every other assertion here while
    # silently dropping a currently-running block (07:30-13:00 at now=12:00).
    assert "whose start_time is earlier than the current local time" in prompt
    assert "Do not move, shift or omit a block solely because its time has passed" in prompt


@pytest.mark.django_db
def test_build_draft_user_message_includes_completion_suffix(user):
    """A history schedule with a ``DailyReview`` whose ``planned_count >
    0`` gets a ``(completed: X/Y)`` suffix on its date header line; a
    schedule without a review (or with ``planned_count == 0``) is silent.
    Pins the analytics-as-context contract for the AI draft prompt.
    """
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)  # Monday
    )

    # History day 1 — has a review with planned_count > 0 → suffix.
    has_review = Schedule.objects.create(
        user=user,
        date=datetime.date(2026, 5, 3),
        status=Schedule.Status.ACTIVE,
    )
    TimeBlock.objects.create(
        schedule=has_review,
        title="Reviewed gym",
        start_time=datetime.time(10, 0),
        end_time=datetime.time(11, 0),
        category="health",
    )
    DailyReview.objects.create(
        schedule=has_review, planned_count=7, completed_count=5
    )

    # History day 2 — no review → no suffix.
    no_review = Schedule.objects.create(
        user=user,
        date=datetime.date(2026, 5, 2),
        status=Schedule.Status.ACTIVE,
    )
    TimeBlock.objects.create(
        schedule=no_review,
        title="No review block",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(10, 0),
        category="other",
    )

    history = list(
        Schedule.objects.filter(user=user)
        .exclude(pk=schedule.pk)
        .order_by("date")
        .prefetch_related("time_blocks")
    )

    msg = build_draft_user_message(
        schedule, None, history, [], datetime.datetime(2026, 5, 4, 7, 30)
    )
    # Suffix appears exactly once — for has_review only.
    assert "(completed: 5/7)" in msg
    assert msg.count("(completed:") == 1
    # Both history dates are still present.
    assert "2026-05-03 (Sunday) (completed: 5/7)" in msg
    assert "2026-05-02 (Saturday)" in msg
    assert "2026-05-02 (Saturday) (completed:" not in msg


@pytest.mark.django_db
def test_build_draft_user_message_rules_section_matches_shared_formatter(user):
    """Parity check (feature 0012): the rules section rendered into the
    draft prompt must match what ``_format_rules_section`` produces for
    the same rule sequence. Pins that the shared formatter is in fact
    shared — a copy-paste regression of the rule loop into the draft
    builder would silently drift this output.
    """
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    rules = [
        type("R", (), {"text": "Rule A"})(),
        type("R", (), {"text": "Rule Б"})(),
    ]
    msg = build_draft_user_message(
        schedule, None, [], rules, datetime.datetime(2026, 5, 4, 7, 30)
    )
    assert _format_rules_section(rules) in msg


@pytest.mark.django_db
def test_build_draft_user_message_without_template(user):
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4)
    )
    msg = build_draft_user_message(
        schedule, None, [], [], datetime.datetime(2026, 5, 4, 8, 0)
    )
    # Should still render without crashing — the view filters this case
    # out at 422 before calling, but the builder must be safe.
    assert "(no template entries)" in msg
    assert "(no recent history)" in msg
    assert "(no active rules)" in msg


def test_draft_add_schema_unchanged_requires_explicit_times():
    """Feature 0067: the draft add schema is untouched — explicit HH:MM start
    and end are still required; no untimed/auto-placement language leaks in."""
    prompt = SYSTEM_PROMPT_DRAFT
    assert "start_time=HH:MM" in prompt
    assert "end_time=HH:MM" in prompt
    # Chat-only auto-placement vocabulary must NOT appear in the draft prompt.
    assert "duration_minutes" not in prompt
    assert "auto" not in prompt.lower() and "automatic" not in prompt.lower()
    assert "complet" not in prompt.lower()
