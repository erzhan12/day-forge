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
    freeze_review_snapshot,
    is_review_snapshot_current,
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
class TestFreezeReviewSnapshot:
    def test_idempotent_preserves_notes(self, past_schedule):
        _make_block(past_schedule, "09:00", "10:00", completed=True)
        _make_block(past_schedule, "10:00", "11:00")

        past_schedule.status = Schedule.Status.REVIEWED
        past_schedule.save(update_fields=["status"])
        review = freeze_review_snapshot(past_schedule, revision=0, now=NOON)
        # A repeated capture must preserve user notes.
        review.notes = "Felt focused"
        review.save(update_fields=["notes"])
        first_updated_at = review.updated_at

        second = freeze_review_snapshot(past_schedule, revision=0, now=NOON)
        assert second.pk == review.pk
        assert second.notes == "Felt focused"
        # auto_now advances on every save, so updated_at strictly increases.
        assert second.updated_at > first_updated_at


@pytest.mark.django_db
def test_review_snapshot_current_requires_status_and_revision(past_schedule):
    review = DailyReview.objects.create(
        schedule=past_schedule, reviewed_revision=past_schedule.revision
    )
    assert not is_review_snapshot_current(past_schedule, review)
    past_schedule.status = Schedule.Status.REVIEWED
    assert is_review_snapshot_current(past_schedule, review)
    past_schedule.revision += 1
    assert not is_review_snapshot_current(past_schedule, review)
    review.reviewed_revision = None
    assert not is_review_snapshot_current(past_schedule, review)
    assert not is_review_snapshot_current(past_schedule, None)


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

    def test_uncompleting_reviewed_day_uses_current_blocks(self, user, streak_settings):
        schedule = self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=1),
            blocks=[("09:00", "10:00", True)],
        )
        review = freeze_review_snapshot(schedule, revision=schedule.revision, now=self.TODAY)
        assert schedule.mark_reviewed_if_active()
        assert review.completion_rate == 1.0
        assert compute_streak(user, today=self.TODAY) == 1

        block = schedule.time_blocks.get()
        block.is_completed = False
        block.save(update_fields=["is_completed"])
        assert schedule.mark_active_on_edit()

        assert compute_streak(user, today=self.TODAY) == 0
        review.refresh_from_db()
        assert review.completion_rate == 1.0

    @pytest.mark.parametrize("status", [Schedule.Status.ACTIVE, Schedule.Status.DRAFT])
    @pytest.mark.parametrize(
        "completed_count, snapshot_planned, snapshot_completed, expected",
        [(4, 5, 0, 1), (3, 5, 5, 0), (5, 0, 0, 1)],
    )
    def test_unreviewed_day_ignores_persisted_review(
        self, user, streak_settings, status, completed_count,
        snapshot_planned, snapshot_completed, expected,
    ):
        schedule = self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=1),
            blocks=[
                (f"{9 + index:02d}:00", f"{10 + index:02d}:00", index < completed_count)
                for index in range(5)
            ],
        )
        schedule.status = status
        schedule.save(update_fields=["status"])
        review = DailyReview.objects.create(
            schedule=schedule,
            planned_count=snapshot_planned,
            completed_count=snapshot_completed,
            notes="Keep these notes",
        )
        snapshot = (review.planned_count, review.completed_count, review.notes, review.updated_at)

        assert compute_streak(user, today=self.TODAY) == expected
        review.refresh_from_db()
        assert (
            review.planned_count, review.completed_count, review.notes, review.updated_at
        ) == snapshot

    @pytest.mark.parametrize(
        "snapshot_planned, snapshot_completed, block_completed, expected",
        [(5, 4, False, 2), (5, 3, True, 0), (0, 0, True, 1)],
    )
    def test_reviewed_day_uses_frozen_snapshot(
        self, user, streak_settings,
        snapshot_planned, snapshot_completed, block_completed, expected,
    ):
        schedule = self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=1),
            blocks=[("09:00", "10:00", block_completed)],
        )
        review = DailyReview.objects.create(
            schedule=schedule,
            planned_count=snapshot_planned,
            completed_count=snapshot_completed,
            reviewed_revision=schedule.revision,
        )
        assert schedule.mark_reviewed_if_active()
        self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=2),
            blocks=[("09:00", "10:00", True)],
        )

        # Deliberately different block counts prove that the frozen snapshot is used.
        assert compute_streak(user, today=self.TODAY) == expected
        review.refresh_from_db()
        assert review.planned_count == snapshot_planned
        assert review.completed_count == snapshot_completed

    def test_stale_reviewed_day_uses_current_blocks(self, user, streak_settings):
        schedule = self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=1),
            blocks=[("09:00", "10:00", False)],
        )
        schedule.mark_reviewed_if_active()
        review = DailyReview.objects.create(
            schedule=schedule,
            planned_count=1,
            completed_count=1,
            reviewed_revision=schedule.revision + 1,
        )
        assert compute_streak(user, today=self.TODAY) == 0
        review.refresh_from_db()
        assert review.completed_count == 1

    @pytest.mark.parametrize("status", Schedule.Status.values)
    def test_empty_day_with_review_skips_without_breaking(self, user, streak_settings, status):
        schedule = Schedule.objects.create(
            user=user,
            date=self.TODAY - datetime.timedelta(days=1),
            status=status,
        )
        DailyReview.objects.create(schedule=schedule, planned_count=1, completed_count=0)
        self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=2),
            blocks=[("09:00", "10:00", True)],
        )

        assert compute_streak(user, today=self.TODAY) == 1

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

    def test_uses_constant_query_count_regardless_of_streak_length(
        self, user, streak_settings, django_assert_num_queries
    ):
        """Regression: the streak walker must NOT issue O(window_days)
        queries. One bulk SELECT for the whole window + the prefetch
        round-trip for ``time_blocks`` is the budget — independent of
        how many days are in the streak. Without the bulk query, this
        test fails with ~30 SELECTs on a long streak."""
        for offset in range(1, 11):  # 10 perfect days, with mixed schedule statuses.
            schedule = self._make_day(
                user,
                self.TODAY - datetime.timedelta(days=offset),
                blocks=[("09:00", "10:00", True)],
            )
            schedule.status = Schedule.Status.values[offset % 3]
            schedule.save(update_fields=["status"])
            DailyReview.objects.create(
                schedule=schedule,
                planned_count=1,
                completed_count=int(schedule.status == Schedule.Status.REVIEWED),
            )
        # Budget: exactly 2 queries —
        #   1) SELECT on Schedule with LEFT OUTER JOIN daily_review
        #      (the select_related), filtered to the window
        #   2) prefetch SELECT on TimeBlock for all returned schedules
        # Tight budget so a regression to per-day SELECTs (30 queries
        # for 10 days, or 31 with the prefetch) trips the test.
        with django_assert_num_queries(2):
            assert compute_streak(user, today=self.TODAY) == 10

    @pytest.mark.parametrize("status", Schedule.Status.values)
    def test_on_the_fly_recompute_when_no_review_row(self, user, streak_settings, status):
        """A day with blocks but no DailyReview row should still count
        toward the streak (streak reflects behaviour, not page-visit
        habits). The on-the-fly recompute does NOT persist."""
        s = self._make_day(
            user,
            self.TODAY - datetime.timedelta(days=1),
            blocks=[("09:00", "10:00", True)],
        )
        s.status = status
        s.save(update_fields=["status"])
        assert not DailyReview.objects.filter(schedule=s).exists()
        assert compute_streak(user, today=self.TODAY) == 1
        # Confirm no DB write happened.
        assert not DailyReview.objects.filter(schedule=s).exists()
