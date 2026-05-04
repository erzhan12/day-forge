"""Tests for ``backend/analytics/services.py``.

Pure aggregator + streak walker tests. No HTTP layer; ``now`` /
``today`` are injected explicitly for determinism.
"""
import datetime

import pytest
from analytics.models import DailyReview
from analytics.services import (
    compute_review_stats,
    compute_streak,
    recompute_review_from_schedule,
)
from schedules.models import Schedule, TimeBlock


def _make_block(schedule, start, end, *, completed=False, category="work"):
    return TimeBlock.objects.create(
        schedule=schedule,
        title="t",
        start_time=start,
        end_time=end,
        category=category,
        is_completed=completed,
    )


@pytest.fixture
def past_schedule(user):
    return Schedule.objects.create(
        user=user, date=datetime.date(2026, 4, 1), status=Schedule.Status.ACTIVE
    )


@pytest.fixture
def today_schedule(user):
    return Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 3), status=Schedule.Status.ACTIVE
    )


# Fixed datetime used as ``now`` throughout the today-aware tests so the
# split between "ended before now" and "still in the future" is
# deterministic.
NOON = datetime.datetime(2026, 5, 3, 12, 0, 0)


@pytest.mark.django_db
class TestComputeReviewStats:
    def test_all_completed_past_day(self, past_schedule):
        _make_block(past_schedule, "09:00", "10:00", completed=True)
        _make_block(past_schedule, "10:00", "11:00", completed=True)
        stats = compute_review_stats(past_schedule, now=NOON)
        assert stats["planned_count"] == 2
        assert stats["completed_count"] == 2
        assert stats["skipped_count"] == 0

    def test_all_uncompleted_past_day(self, past_schedule):
        _make_block(past_schedule, "09:00", "10:00")
        _make_block(past_schedule, "10:00", "11:00")
        stats = compute_review_stats(past_schedule, now=NOON)
        assert stats["planned_count"] == 2
        assert stats["completed_count"] == 0
        assert stats["skipped_count"] == 2

    def test_mixed_past_day(self, past_schedule):
        _make_block(past_schedule, "09:00", "10:00", completed=True)
        _make_block(past_schedule, "10:00", "11:00")
        _make_block(past_schedule, "11:00", "12:00", completed=True)
        stats = compute_review_stats(past_schedule, now=NOON)
        assert stats["planned_count"] == 3
        assert stats["completed_count"] == 2
        assert stats["skipped_count"] == 1

    def test_today_only_ended_blocks_skipped(self, today_schedule):
        # Two blocks: one ending before noon (skipped), one ending after
        # noon (still active, not skipped).
        _make_block(today_schedule, "09:00", "10:00")
        _make_block(today_schedule, "14:00", "15:00")
        stats = compute_review_stats(today_schedule, now=NOON)
        assert stats["planned_count"] == 2
        assert stats["completed_count"] == 0
        assert stats["skipped_count"] == 1

    def test_today_all_ended_uncompleted_are_skipped(self, today_schedule):
        _make_block(today_schedule, "09:00", "10:00")
        _make_block(today_schedule, "10:00", "11:00")
        stats = compute_review_stats(today_schedule, now=NOON)
        assert stats["skipped_count"] == 2

    def test_empty_schedule_is_rest_day(self, past_schedule):
        stats = compute_review_stats(past_schedule, now=NOON)
        assert stats == {
            "planned_count": 0,
            "completed_count": 0,
            "skipped_count": 0,
            "planned_minutes_by_category": {
                "work": 0, "personal": 0, "health": 0, "other": 0
            },
            "completed_minutes_by_category": {
                "work": 0, "personal": 0, "health": 0, "other": 0
            },
        }

    def test_category_aggregates_sum_correctly(self, past_schedule):
        _make_block(
            past_schedule, "09:00", "10:00", completed=True, category="work"
        )
        _make_block(
            past_schedule, "10:00", "11:30", completed=True, category="work"
        )
        _make_block(
            past_schedule,
            "12:00",
            "12:30",
            completed=False,
            category="health",
        )
        stats = compute_review_stats(past_schedule, now=NOON)
        # 60 + 90 = 150 work, 30 health planned; 150 work completed.
        assert stats["planned_minutes_by_category"]["work"] == 150
        assert stats["planned_minutes_by_category"]["health"] == 30
        assert stats["planned_minutes_by_category"]["personal"] == 0
        assert stats["completed_minutes_by_category"]["work"] == 150
        assert stats["completed_minutes_by_category"]["health"] == 0


@pytest.mark.django_db
class TestRecomputeReviewFromSchedule:
    def test_idempotent_preserves_notes(self, past_schedule):
        _make_block(past_schedule, "09:00", "10:00", completed=True)
        _make_block(past_schedule, "10:00", "11:00")

        review = recompute_review_from_schedule(past_schedule, now=NOON)
        # User adds notes; recompute must NOT clobber them.
        review.notes = "Felt focused"
        review.save(update_fields=["notes"])
        first_updated_at = review.updated_at

        second = recompute_review_from_schedule(past_schedule, now=NOON)
        assert second.pk == review.pk
        assert second.notes == "Felt focused"
        # auto_now advances on every save, so updated_at strictly increases.
        assert second.updated_at > first_updated_at


@pytest.fixture
def streak_settings(settings):
    """Pin the streak knobs for the streak tests so a future env-driven
    default change can't silently break them."""
    settings.ANALYTICS_STREAK_THRESHOLD = 0.8
    settings.ANALYTICS_STREAK_WINDOW_DAYS = 30
    return settings


@pytest.mark.django_db
class TestComputeStreak:
    TODAY = datetime.date(2026, 5, 3)

    def _make_day(self, user, date, *, blocks):
        s = Schedule.objects.create(
            user=user, date=date, status=Schedule.Status.ACTIVE
        )
        for start, end, completed in blocks:
            _make_block(s, start, end, completed=completed)
        return s

    def test_cold_start_no_schedules(self, user, streak_settings):
        assert compute_streak(user, today=self.TODAY) == 0

    def test_five_consecutive_above_threshold(self, user, streak_settings):
        for offset in range(1, 6):
            self._make_day(
                user,
                self.TODAY - datetime.timedelta(days=offset),
                blocks=[
                    ("09:00", "10:00", True),
                    ("10:00", "11:00", True),
                    ("11:00", "12:00", True),
                    ("12:00", "13:00", True),
                    ("13:00", "14:00", False),
                ],
            )
        assert compute_streak(user, today=self.TODAY) == 5

    def test_gap_day_breaks_streak(self, user, streak_settings):
        # Three days in a row OK, then a gap (no Schedule row), then
        # another OK day. Streak = days since today until the gap = 3.
        for offset in [1, 2, 3, 5]:
            self._make_day(
                user,
                self.TODAY - datetime.timedelta(days=offset),
                blocks=[("09:00", "10:00", True)],
            )
        # Day 4 is a gap.
        assert compute_streak(user, today=self.TODAY) == 3

    def test_zero_block_day_skips_without_breaking(self, user, streak_settings):
        # 5 OK days; day-3 has zero blocks (rest day).
        for offset in [1, 2, 4, 5, 6]:
            self._make_day(
                user,
                self.TODAY - datetime.timedelta(days=offset),
                blocks=[("09:00", "10:00", True)],
            )
        # Day 3 is a rest day (Schedule exists but no blocks).
        Schedule.objects.create(
            user=user,
            date=self.TODAY - datetime.timedelta(days=3),
            status=Schedule.Status.ACTIVE,
        )
        # Streak counts the 5 active days; rest day didn't break or count.
        assert compute_streak(user, today=self.TODAY) == 5

    def test_below_threshold_breaks(self, user, streak_settings):
        # 1 OK day, then 1 below-threshold day, then more OK days.
        self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=1),
            blocks=[("09:00", "10:00", True), ("10:00", "11:00", True)],
        )
        # Day 2: 0/2 completed = 0% < 80% → break.
        self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=2),
            blocks=[("09:00", "10:00", False), ("10:00", "11:00", False)],
        )
        self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=3),
            blocks=[("09:00", "10:00", True)],
        )
        assert compute_streak(user, today=self.TODAY) == 1

    def test_window_caps_streak(self, user, settings):
        # 60 consecutive perfect days, but window is 3 → streak == 3.
        settings.ANALYTICS_STREAK_THRESHOLD = 0.8
        settings.ANALYTICS_STREAK_WINDOW_DAYS = 3
        for offset in range(1, 61):
            self._make_day(
                user,
                self.TODAY - datetime.timedelta(days=offset),
                blocks=[("09:00", "10:00", True)],
            )
        assert compute_streak(user, today=self.TODAY) == 3

    def test_on_the_fly_recompute_when_no_review_row(self, user, streak_settings):
        """A day with blocks but no DailyReview row should still count
        toward the streak (streak reflects behaviour, not page-visit
        habits). The on-the-fly recompute does NOT persist."""
        s = self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=1),
            blocks=[("09:00", "10:00", True)],
        )
        assert not DailyReview.objects.filter(schedule=s).exists()
        assert compute_streak(user, today=self.TODAY) == 1
        # Confirm no DB write happened.
        assert not DailyReview.objects.filter(schedule=s).exists()
