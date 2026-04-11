import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def assign_default_user(apps, schema_editor):
    """Assign orphaned schedules to the first superuser (or first user)."""
    User = apps.get_model("auth", "User")
    Schedule = apps.get_model("schedules", "Schedule")
    orphaned = Schedule.objects.filter(user__isnull=True)
    if not orphaned.exists():
        return
    user = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if user:
        orphaned.update(user=user)
    else:
        # No users exist — delete orphaned schedules so migration can proceed
        orphaned.delete()


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
        # 2. Assign existing schedules to a default user
        migrations.RunPython(assign_default_user, migrations.RunPython.noop),
        # 3. Remove old unique constraint on date
        migrations.AlterField(
            model_name="schedule",
            name="date",
            field=models.DateField(),
        ),
        # 4. Make user non-nullable
        migrations.AlterField(
            model_name="schedule",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="schedules",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 5. Add composite unique constraint
        migrations.AddConstraint(
            model_name="schedule",
            constraint=models.UniqueConstraint(
                fields=["user", "date"], name="unique_user_date"
            ),
        ),
    ]
