"""Tests for ``DailyReview`` model behaviour.

Pure-property tests; the upsert/recompute logic lives in
``analytics/services.py`` and is covered by ``test_analytics_services.py``.
"""
import datetime

import pytest
from analytics.models import DailyReview
from schedules.models import Schedule


@pytest.fixture
def schedule_for_review(user):
    return Schedule.objects.create(
        user=user,
        date=datetime.date(2026, 5, 1),
        status=Schedule.Status.ACTIVE,
    )


@pytest.mark.django_db
class TestCompletionRate:
    def test_partial_completion(self, schedule_for_review):
        r = DailyReview.objects.create(
            schedule=schedule_for_review, planned_count=4, completed_count=2
        )
        assert r.completion_rate == 0.5

    def test_full_completion(self, schedule_for_review):
        r = DailyReview.objects.create(
            schedule=schedule_for_review, planned_count=3, completed_count=3
        )
        assert r.completion_rate == 1.0

    def test_zero_planned_returns_none(self, schedule_for_review):
        """A rest day (no blocks planned) is distinct from 0% completed —
        callers (streak walker, UI) need to tell them apart."""
        r = DailyReview.objects.create(
            schedule=schedule_for_review, planned_count=0, completed_count=0
        )
        assert r.completion_rate is None
