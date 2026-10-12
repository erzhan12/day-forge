"""Data backfill for review snapshots created before revision tagging."""

import datetime
import importlib
from types import SimpleNamespace

import pytest
from analytics.models import DailyReview
from django.apps import apps
from django.db import connection
from schedules.models import Schedule


@pytest.mark.django_db
def test_backfill_tags_only_existing_reviewed_snapshots(user):
    reviewed = Schedule.objects.create(
        user=user, date=datetime.date(2026, 4, 1),
        status=Schedule.Status.REVIEWED, revision=7,
    )
    active = Schedule.objects.create(
        user=user, date=datetime.date(2026, 4, 2),
        status=Schedule.Status.ACTIVE, revision=3,
    )
    frozen = DailyReview.objects.create(
        schedule=reviewed, completed_count=2, notes="Keep me"
    )
    current = DailyReview.objects.create(schedule=active, completed_count=1)

    migration = importlib.import_module(
        "analytics.migrations.0003_dailyreview_reviewed_revision"
    )
    migration.backfill_reviewed_revision(
        apps, SimpleNamespace(connection=connection)
    )

    frozen.refresh_from_db()
    current.refresh_from_db()
    assert frozen.reviewed_revision == 7
    assert frozen.completed_count == 2
    assert frozen.notes == "Keep me"
    assert current.reviewed_revision is None
