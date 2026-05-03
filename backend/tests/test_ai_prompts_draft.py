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
    _runtime_block_to_dict,
    _template_entry_to_dict,
    build_draft_user_message,
)
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Rule, Template


def test_system_prompt_only_allows_add():
    assert "add" in SYSTEM_PROMPT_DRAFT
    assert "No move/remove/resize" in SYSTEM_PROMPT_DRAFT


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
