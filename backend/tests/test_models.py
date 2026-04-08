import datetime

import pytest
from ai.models import AIInteraction
from analytics.models import DailyReview
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Rule, Template


@pytest.fixture
def user(db):
    return User.objects.create_user(username="modeluser", password="pass")


@pytest.fixture
def schedule(user):
    return Schedule.objects.create(date=datetime.date(2026, 4, 7), user=user)


@pytest.fixture
def time_block(schedule):
    return TimeBlock.objects.create(
        schedule=schedule,
        title="Deep work",
        start_time=datetime.time(9, 0),
        end_time=datetime.time(12, 0),
        category="work",
    )


# --- Schedule ---


@pytest.mark.django_db
class TestSchedule:
    def test_create(self, user):
        s = Schedule.objects.create(date=datetime.date(2026, 1, 1), user=user)
        assert str(s) == "2026-01-01 (draft)"

    def test_unique_user_date(self, schedule):
        with pytest.raises(IntegrityError):
            Schedule.objects.create(date=schedule.date, user=schedule.user)

    def test_same_date_different_users(self, schedule):
        other = User.objects.create_user(username="other", password="pass")
        Schedule.objects.create(date=schedule.date, user=other)  # should not raise

    def test_ordering(self, user):
        s1 = Schedule.objects.create(date=datetime.date(2026, 1, 1), user=user)
        s2 = Schedule.objects.create(date=datetime.date(2026, 1, 2), user=user)
        results = list(Schedule.objects.all())
        assert results == [s2, s1]  # newest first


# --- TimeBlock ---


@pytest.mark.django_db
class TestTimeBlock:
    def test_create(self, time_block):
        assert str(time_block) == "Deep work (09:00:00-12:00:00)"

    def test_ordering(self, schedule):
        b2 = TimeBlock.objects.create(
            schedule=schedule, title="B", start_time="10:00", end_time="11:00"
        )
        b1 = TimeBlock.objects.create(
            schedule=schedule, title="A", start_time="09:00", end_time="10:00"
        )
        results = list(schedule.time_blocks.all())
        assert results == [b1, b2]

    def test_cascade_delete(self, schedule, time_block):
        schedule.delete()
        assert TimeBlock.objects.count() == 0

    def test_five_minute_granularity_valid(self, schedule):
        block = TimeBlock(
            schedule=schedule, title="Test", start_time="09:00", end_time="09:30"
        )
        block.full_clean()  # should not raise

    def test_five_minute_granularity_invalid(self, schedule):
        block = TimeBlock(
            schedule=schedule, title="Test", start_time="09:07", end_time="09:30"
        )
        with pytest.raises(ValidationError):
            block.full_clean()

    def test_start_before_end(self, schedule):
        block = TimeBlock(
            schedule=schedule, title="Test", start_time="10:00", end_time="09:00"
        )
        with pytest.raises(ValidationError):
            block.full_clean()

    def test_start_equals_end(self, schedule):
        block = TimeBlock(
            schedule=schedule, title="Test", start_time="10:00", end_time="10:00"
        )
        with pytest.raises(ValidationError):
            block.full_clean()


# --- Template ---


@pytest.mark.django_db
class TestTemplate:
    def test_create_with_blocks(self, db):
        t = Template.objects.create(
            name="Weekday",
            type="weekday",
            blocks=[{"title": "Work", "start_time": "09:00", "end_time": "17:00"}],
        )
        assert str(t) == "Weekday (weekday)"
        assert len(t.blocks) == 1


# --- Rule ---


@pytest.mark.django_db
class TestRule:
    def test_ordering_by_priority(self, db):
        r_low = Rule.objects.create(text="Low priority", priority=1)
        r_high = Rule.objects.create(text="High priority", priority=10)
        results = list(Rule.objects.all())
        assert results == [r_high, r_low]

    def test_str_truncation(self, db):
        long_text = "x" * 200
        r = Rule.objects.create(text=long_text)
        assert len(str(r)) == 80


# --- AIInteraction ---


@pytest.mark.django_db
class TestAIInteraction:
    def test_create(self, schedule):
        ai = AIInteraction.objects.create(
            schedule=schedule,
            user_command="add standup at 10:00",
            ai_response='{"actions": []}',
            actions_json=[],
        )
        assert "add standup" in str(ai)

    def test_cascade_on_schedule_delete(self, schedule):
        AIInteraction.objects.create(
            schedule=schedule, user_command="test", ai_response="test"
        )
        schedule.delete()
        assert AIInteraction.objects.count() == 0


# --- DailyReview ---


@pytest.mark.django_db
class TestDailyReview:
    def test_create(self, schedule):
        review = DailyReview.objects.create(
            schedule=schedule, planned_count=5, completed_count=3, skipped_count=2
        )
        assert "3/5" in str(review)

    def test_one_to_one(self, schedule):
        DailyReview.objects.create(schedule=schedule)
        with pytest.raises(IntegrityError):
            DailyReview.objects.create(schedule=schedule)
