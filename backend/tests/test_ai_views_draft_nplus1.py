"""Regression coverage for draft-history ``DailyReview`` query loading."""

import datetime
import json

import pytest
from ai.prompts import build_draft_user_message
from analytics.models import DailyReview
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from schedules.models import Schedule
from templates_mgr.models import Template

TARGET_DATE = datetime.date(2026, 5, 4)
URL = f"/api/ai/schedules/{TARGET_DATE.isoformat()}/generate-draft/"


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("Message", (), {"content": content})()


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    async def create(self, **_kwargs):
        return _FakeResponse(
            json.dumps(
                {
                    "actions": [
                        {
                            "type": "add",
                            "title": "Generated block",
                            "start_time": "09:00",
                            "end_time": "10:00",
                            "category": "work",
                        }
                    ],
                    "explanation": "Generated draft",
                }
            )
        )


class _FakeClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": _FakeCompletions()})()


@pytest.fixture
def draft_template(user):
    return Template.objects.create(
        user=user,
        name="Weekday",
        type=Template.Type.WEEKDAY,
        blocks=[],
    )


@pytest.fixture
def draft_history(user):
    schedules = []
    for days_ago in range(3, 0, -1):
        schedule = Schedule.objects.create(
            user=user,
            date=TARGET_DATE - datetime.timedelta(days=days_ago),
            status=Schedule.Status.REVIEWED,
        )
        DailyReview.objects.create(
            schedule=schedule,
            planned_count=4,
            completed_count=days_ago,
        )
        schedules.append(schedule)
    return schedules


def _daily_review_query_count(ctx: CaptureQueriesContext) -> int:
    return sum("analytics_dailyreview" in query["sql"] for query in ctx.captured_queries)


@pytest.mark.django_db
def test_generate_draft_selects_history_reviews_in_one_query(
    auth_client,
    draft_template,
    draft_history,
    monkeypatch,
    settings,
):
    """The async view must not lazily load reverse one-to-one reviews."""
    settings.LLM_API_KEY = "sk-test"
    settings.LLM_HISTORY_DAYS = 3
    monkeypatch.setattr("ai.service._get_client", _FakeClient)

    with CaptureQueriesContext(connection) as ctx:
        response = auth_client.post(URL, "", content_type="application/json")

    assert response.status_code == 200
    assert _daily_review_query_count(ctx) == 1


@pytest.mark.django_db
def test_prompt_builder_proves_daily_review_nplus1_and_eager_load_fix(
    user,
    draft_template,
    draft_history,
):
    """A sync proof documents the N lazy queries avoided by the view."""
    schedule = Schedule.objects.create(user=user, date=TARGET_DATE)
    history_filter = {
        "user": user,
        "date__lt": TARGET_DATE,
        "date__gte": TARGET_DATE - datetime.timedelta(days=3),
        "status__in": [Schedule.Status.ACTIVE, Schedule.Status.REVIEWED],
    }
    now = timezone.make_aware(datetime.datetime(2026, 5, 4, 8, 0))

    with CaptureQueriesContext(connection) as lazy_ctx:
        lazy_history = list(Schedule.objects.filter(**history_filter).order_by("date"))
        build_draft_user_message(schedule, draft_template, lazy_history, [], now)

    with CaptureQueriesContext(connection) as eager_ctx:
        eager_history = list(
            Schedule.objects.filter(**history_filter)
            .order_by("date")
            .select_related("daily_review")
        )
        build_draft_user_message(schedule, draft_template, eager_history, [], now)

    # One lazy daily_review query per history row iterated; the eager
    # select_related collapses them to one. Couple the expected lazy count
    # to the actual history size so growing the fixture can't silently
    # weaken the assertion.
    assert _daily_review_query_count(lazy_ctx) == len(lazy_history)
    assert _daily_review_query_count(eager_ctx) == 1
