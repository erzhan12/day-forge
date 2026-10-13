"""Cross-feature checks for saved timezone semantics and naive block times."""

import datetime
import json
from unittest.mock import patch

import pytest
from analytics.services import compute_review_stats, compute_streak
from django.urls import reverse
from schedules.models import Schedule, TimeBlock, UserScheduleSettings

pytestmark = pytest.mark.django_db

INSTANT = datetime.datetime(2026, 5, 7, 22, 30, tzinfo=datetime.UTC)


def _block(schedule, *, start, end, completed=False):
    return TimeBlock.objects.create(
        schedule=schedule,
        title="Existing block",
        start_time=start,
        end_time=end,
        category="work",
        is_completed=completed,
    )


def test_review_stats_default_uses_saved_local_date_and_time(user):
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 8), status=Schedule.Status.ACTIVE
    )
    _block(schedule, start="00:30", end="01:00")
    _block(schedule, start="02:00", end="03:00")
    stored = UserScheduleSettings.objects.create(user=user, time_zone="UTC")

    with patch("schedules.window.timezone.now", return_value=INSTANT):
        assert compute_review_stats(schedule)["skipped_count"] == 0
        stored.time_zone = "Asia/Qatar"
        stored.save()
        assert compute_review_stats(schedule)["skipped_count"] == 1


def test_streak_default_starts_from_saved_local_today(user):
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 7), status=Schedule.Status.ACTIVE
    )
    _block(schedule, start="09:00", end="10:00", completed=True)
    stored = UserScheduleSettings.objects.create(user=user, time_zone="UTC")

    with patch("schedules.window.timezone.now", return_value=INSTANT):
        assert compute_streak(user) == 0
        stored.time_zone = "Asia/Qatar"
        stored.save()
        assert compute_streak(user) == 1


def test_timezone_setting_change_keeps_existing_block_clock_times(user, auth_client):
    schedule = Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 8), status=Schedule.Status.ACTIVE
    )
    block = _block(schedule, start="09:15", end="10:45")
    initial_revision = schedule.revision

    response = auth_client.patch(
        reverse("schedule_settings"),
        data=json.dumps({"time_zone": "Asia/Qatar"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["time_zone"] == "Asia/Qatar"
    block.refresh_from_db()
    schedule.refresh_from_db()
    assert (block.start_time, block.end_time) == (
        datetime.time(9, 15), datetime.time(10, 45)
    )
    assert schedule.date == datetime.date(2026, 5, 8)
    assert schedule.revision == initial_revision
