"""Unit tests for the shared owner-scoped schedule/day reader (feature 0088).

``read_schedule_day`` is extracted from ``schedules.views._read_schedule_page``
so the export API (and any future read-only caller) can capture a day's
schedule and ordered blocks without reserving the SQLite writer or
bootstrapping first-use rows. See ``tests/test_schedule_mutations_sqlite.py``
for the concurrency/snapshot-coherence coverage of this same function.
"""

import datetime

import pytest
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock
from schedules.reads import read_schedule_day

pytestmark = pytest.mark.django_db


def test_absent_day_returns_none_without_creating_rows(user):
    result = read_schedule_day(user, datetime.date(2026, 10, 10))
    assert result is None
    assert not Schedule.objects.filter(user=user).exists()


def test_owner_scoping_excludes_another_users_schedule_on_the_same_date(user):
    other = User.objects.create_user(username="reads-other-owner")
    Schedule.objects.create(user=other, date=datetime.date(2026, 10, 10))
    assert read_schedule_day(user, datetime.date(2026, 10, 10)) is None


def test_returns_owned_schedule_and_blocks(user):
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 10, 10))
    block = TimeBlock.objects.create(
        schedule=schedule, title="Gym", start_time="09:00", end_time="10:00"
    )
    result = read_schedule_day(user, datetime.date(2026, 10, 10))
    assert result is not None
    returned_schedule, blocks = result
    assert returned_schedule.pk == schedule.pk
    assert [b.pk for b in blocks] == [block.pk]


def test_blocks_are_deterministically_ordered(user):
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 10, 10))
    # Create out of order and with tied (start_time, sort_order) to exercise
    # the full ("start_time", "sort_order", "id") ordering tuple.
    third = TimeBlock.objects.create(
        schedule=schedule, title="Third", start_time="09:00", end_time="09:30", sort_order=0
    )
    first = TimeBlock.objects.create(
        schedule=schedule, title="First", start_time="08:00", end_time="08:30", sort_order=1
    )
    second = TimeBlock.objects.create(
        schedule=schedule, title="Second", start_time="09:00", end_time="09:15", sort_order=0
    )
    _, blocks = read_schedule_day(user, datetime.date(2026, 10, 10))
    assert [b.pk for b in blocks] == [first.pk, third.pk, second.pk]
