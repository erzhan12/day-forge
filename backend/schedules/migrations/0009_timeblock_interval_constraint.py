from django.db import migrations, models


def check_existing_intervals(apps, schema_editor):
    """Refuse invalid legacy rows without changing or exposing their contents."""
    blocks = apps.get_model("schedules", "TimeBlock")
    invalid_count = (
        blocks.objects.using(schema_editor.connection.alias)
        .filter(start_time__gte=models.F("end_time"))
        .count()
    )
    if invalid_count:
        raise RuntimeError(
            f"Cannot add timeblock_start_lt_end: {invalid_count} invalid intervals. "
            "Review these rows before running the migration; no rows were changed."
        )


class Migration(migrations.Migration):
    dependencies = [("schedules", "0008_schedule_revision")]

    operations = [
        migrations.RunPython(check_existing_intervals, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="timeblock",
            constraint=models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F("end_time")),
                name="timeblock_start_lt_end",
            ),
        ),
    ]
