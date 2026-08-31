import datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_0007_backfills_existing_settings_time_zone_to_utc():
    executor = MigrationExecutor(connection)
    old_target = [("schedules", "0006_category_alter_timeblock_category")]
    head_target = [("schedules", "0007_userschedulesettings_time_zone")]
    executor.migrate(old_target)
    try:
        old_apps = executor.loader.project_state(old_target).apps
        OldSettings = old_apps.get_model("schedules", "UserScheduleSettings")
        user = get_user_model().objects.create_user(username="migration-zone-user")
        row = OldSettings.objects.create(
            user_id=user.id, day_start=datetime.time(8, 0), day_end=datetime.time(20, 0)
        )
        executor = MigrationExecutor(connection)
        executor.migrate(head_target)
        new_apps = executor.loader.project_state(head_target).apps
        NewSettings = new_apps.get_model("schedules", "UserScheduleSettings")
        migrated = NewSettings.objects.get(pk=row.pk)
        assert migrated.time_zone == "UTC"
        assert migrated.day_start == datetime.time(8, 0)
        assert migrated.day_end == datetime.time(20, 0)
        assert migrated.user_id == user.id
    finally:
        MigrationExecutor(connection).migrate(head_target)
