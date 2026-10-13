from django.db import migrations, models
from django.db.models import OuterRef, Subquery


def backfill_reviewed_revision(apps, schema_editor):
    DailyReview = apps.get_model("analytics", "DailyReview")
    Schedule = apps.get_model("schedules", "Schedule")
    DailyReview.objects.using(schema_editor.connection.alias).filter(
        schedule__status="reviewed"
    ).update(
        reviewed_revision=Subquery(
            Schedule.objects.using(schema_editor.connection.alias)
            .filter(pk=OuterRef("schedule_id"))
            .values("revision")[:1]
        )
    )


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0002_review_aggregates"),
        ("schedules", "0008_schedule_revision"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailyreview",
            name="reviewed_revision",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_reviewed_revision, migrations.RunPython.noop),
    ]
