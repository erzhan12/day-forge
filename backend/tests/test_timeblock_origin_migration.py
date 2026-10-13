"""Existing blocks receive no invented provenance during the origin migration."""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_0010_classifies_old_rows_unknown_and_new_rows_manual():
    executor = MigrationExecutor(connection)
    old_target = [("schedules", "0009_timeblock_interval_constraint")]
    new_target = [("schedules", "0010_timeblock_origin")]
    executor.migrate(old_target)
    try:
        old_apps = executor.loader.project_state(old_target).apps
        OldSchedule = old_apps.get_model("schedules", "Schedule")
        OldBlock = old_apps.get_model("schedules", "TimeBlock")
        user = get_user_model().objects.create_user(username="origin-migration-user")
        schedule = OldSchedule.objects.create(
            user_id=user.id,
            date=datetime.date(2026, 4, 18),
            status="reviewed",
            revision=7,
        )
        old = OldBlock.objects.create(
            schedule_id=schedule.id,
            title="Unknown source",
            start_time=datetime.time(9, 0),
            end_time=datetime.time(10, 0),
            category="work",
        )

        executor = MigrationExecutor(connection)
        executor.migrate(new_target)
        new_apps = executor.loader.project_state(new_target).apps
        NewBlock = new_apps.get_model("schedules", "TimeBlock")
        migrated = NewBlock.objects.get(pk=old.pk)
        migrated_schedule = new_apps.get_model("schedules", "Schedule").objects.get(pk=schedule.pk)
        assert migrated.origin == "unknown"
        assert migrated.title == old.title
        assert migrated.start_time == old.start_time
        assert migrated.end_time == old.end_time
        assert migrated_schedule.status == "reviewed"
        assert migrated_schedule.revision == 7
        new = NewBlock.objects.create(
            schedule_id=schedule.id,
            title="Known manual",
            start_time=datetime.time(10, 0),
            end_time=datetime.time(11, 0),
            category="work",
        )
        assert new.origin == "manual"
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
