from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("schedules", "0009_timeblock_interval_constraint")]

    operations = [
        # Existing titles have no trustworthy source. Keep them out of AI
        # context until a user recreates them through a known entry point.
        migrations.AddField(
            model_name="timeblock",
            name="origin",
            field=models.CharField(
                choices=[
                    ("manual", "Manual"),
                    ("calendar", "Calendar import"),
                    ("unknown", "Legacy or unverified"),
                ],
                default="unknown",
                max_length=8,
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="timeblock",
            name="origin",
            field=models.CharField(
                choices=[
                    ("manual", "Manual"),
                    ("calendar", "Calendar import"),
                    ("unknown", "Legacy or unverified"),
                ],
                default="manual",
                max_length=8,
            ),
        ),
    ]
