# Generated manually for feature 0053.
import datetime

from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q


class Migration(migrations.Migration):
    dependencies = [("schedules", "0004_remove_timeblock_schedules_t_schedul_8d6c7c_idx_and_more")]

    operations = [
        migrations.CreateModel(
            name="UserScheduleSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day_start", models.TimeField(default=datetime.time(6, 0))),
                ("day_end", models.TimeField(default=datetime.time(23, 0))),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="schedule_settings", to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.CheckConstraint(condition=Q(("day_start__lt", F("day_end"))), name="schedule_window_start_lt_end")]},
        ),
    ]
