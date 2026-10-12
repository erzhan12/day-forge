from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("schedules", "0007_userschedulesettings_time_zone")]

    operations = [
        migrations.AddField(
            model_name="schedule",
            name="revision",
            field=models.PositiveBigIntegerField(default=0, editable=False),
        ),
    ]
