"""Add per-user ownership to ``Template`` and ``Rule``.

Both models were originally global (no user FK). The migration:

1. Adds a nullable ``user`` FK to each model.
2. **Wipes orphan rows** — every existing template/rule has no owner under
   the global model. Synthesising one (e.g. "first superuser") would
   silently bind another user's identity to data they didn't author, so
   we delete instead. Operators re-run ``seed_templates --user <name>``
   per user post-migration to repopulate.
3. Switches the FK to ``null=False``.
4. Adds the unique ``(user, type)`` constraint on ``Template`` so each
   user has at most one weekday and one weekend template — eliminates the
   ambiguous ``.filter(type=...).first()`` selection at draft time.

Single-developer impact: regenerate seed locally; production has not been
deployed yet.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def wipe_orphan_rows(apps, schema_editor):
    Template = apps.get_model("templates_mgr", "Template")
    Rule = apps.get_model("templates_mgr", "Rule")
    Template.objects.filter(user__isnull=True).delete()
    Rule.objects.filter(user__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("templates_mgr", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="template",
            name="user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="templates",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="rule",
            name="user",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rules",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(wipe_orphan_rows, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="template",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="templates",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="rule",
            name="user",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="rules",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="template",
            constraint=models.UniqueConstraint(
                fields=["user", "type"], name="unique_user_template_type"
            ),
        ),
    ]
