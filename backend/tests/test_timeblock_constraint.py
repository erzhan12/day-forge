import datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from schedules.models import Schedule, TimeBlock


@pytest.mark.django_db
@pytest.mark.parametrize("end", [datetime.time(9), datetime.time(8, 59)])
def test_database_rejects_invalid_interval_on_bulk_create(user, end):
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 10, 17))
    with pytest.raises(IntegrityError), transaction.atomic():
        TimeBlock.objects.bulk_create(
            [
                TimeBlock(
                    schedule=schedule, title="Invalid", start_time=datetime.time(9), end_time=end
                )
            ]
        )
    assert not schedule.time_blocks.exists()


@pytest.mark.django_db
def test_database_rejects_invalid_queryset_update_and_preserves_off_grid(user):
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 10, 17))
    block = TimeBlock.objects.create(
        schedule=schedule,
        title="Imported",
        start_time=datetime.time(9, 7),
        end_time=datetime.time(9, 23),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        TimeBlock.objects.filter(pk=block.pk).update(end_time=datetime.time(9, 7))
    block.refresh_from_db()
    assert (block.start_time, block.end_time) == (datetime.time(9, 7), datetime.time(9, 23))


@pytest.mark.django_db(transaction=True)
def test_migration_refuses_legacy_invalid_rows_without_repair():
    previous = [("schedules", "0008_schedule_revision")]
    target = [("schedules", "0009_timeblock_interval_constraint")]
    executor = MigrationExecutor(connection)
    executor.migrate(previous)
    old_apps = executor.loader.project_state(previous).apps
    old_blocks = old_apps.get_model("schedules", "TimeBlock")
    invalid_id = None
    try:
        user = get_user_model().objects.create_user(username="r07-migration-check")
        schedule = old_apps.get_model("schedules", "Schedule").objects.create(
            user_id=user.pk, date=datetime.date(2026, 10, 17)
        )
        valid = old_blocks.objects.create(
            schedule=schedule,
            title="Imported",
            start_time=datetime.time(9, 7),
            end_time=datetime.time(9, 23),
        )
        invalid = old_blocks.objects.create(
            schedule=schedule,
            title="Legacy invalid",
            start_time=datetime.time(10),
            end_time=datetime.time(10),
        )
        invalid_id = invalid.pk
        with pytest.raises(RuntimeError, match="1 invalid intervals"):
            MigrationExecutor(connection).migrate(target)
        assert old_blocks.objects.get(pk=invalid_id).end_time == datetime.time(10)
        assert old_blocks.objects.count() == 2
        # Explicit test cleanup allows the unchanged valid row to migrate.
        invalid.delete()
        invalid_id = None
        target_executor = MigrationExecutor(connection)
        target_executor.migrate(target)
        migrated = target_executor.loader.project_state(target).apps.get_model(
            "schedules", "TimeBlock"
        ).objects.get(pk=valid.pk)
        assert (migrated.start_time, migrated.end_time) == (
            datetime.time(9, 7),
            datetime.time(9, 23),
        )
    finally:
        if invalid_id is not None:
            old_blocks.objects.filter(pk=invalid_id).delete()
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
