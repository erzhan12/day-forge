import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("schedules", "0001_initial"),
    ]

    operations = [
        # 1. Add nullable user FK
        migrations.AddField(
            model_name="schedule",
            name="user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="schedules",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 2. Remove old unique constraint on date
        migrations.AlterField(
            model_name="schedule",
            name="date",
            field=models.DateField(),
        ),
        # 3. Make user non-nullable
        migrations.AlterField(
            model_name="schedule",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="schedules",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 4. Add composite unique constraint
        migrations.AddConstraint(
            model_name="schedule",
            constraint=models.UniqueConstraint(
                fields=["user", "date"], name="unique_user_date"
            ),
        ),
    ]
