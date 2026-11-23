"""Feature 0106: Education stops sharing Health's emerald colour.

Recolours a user's Education category to ``amber`` only when that user has
both Health and Education (matched by label under the same normalisation as
``unique_user_category_label_ci``) and both are ``emerald``. Nothing else
changes. Labels, not slugs, identify the rows: slugs are frozen at creation
while labels can be renamed.

The reverse is a no-op: unapplying leaves the colours as they are, because
no predicate can tell a migrated row from a deliberate later amber. Recovery
is in docs/features/0106_PLAN.md (C.10). Re-applying after an unapply is safe
except for a user who set Education back to emerald while Health is also
emerald: that row turns amber again.
"""

from django.db import migrations
from django.db.models.functions import Lower, Trim

SHARED_COLOUR = "emerald"
EDUCATION_COLOUR = "amber"


def recolour_education(apps, schema_editor):
    Category = apps.get_model("schedules", "Category")
    db = schema_editor.connection.alias
    rows = (
        Category.objects.using(db)
        .annotate(normalised=Lower(Trim("label")))
        .filter(normalised__in=("health", "education"), color_id=SHARED_COLOUR)
        .values_list("user_id", "normalised", "id")
    )
    by_user = {}
    for user_id, normalised, pk in rows:
        by_user.setdefault(user_id, {})[normalised] = pk
    education_ids = [
        labels["education"]
        for labels in by_user.values()
        if "health" in labels and "education" in labels
    ]
    if education_ids:
        Category.objects.using(db).filter(id__in=education_ids).update(
            color_id=EDUCATION_COLOUR
        )


class Migration(migrations.Migration):
    dependencies = [
        ("schedules", "0011_personalexporttoken"),
    ]

    operations = [
        migrations.RunPython(recolour_education, migrations.RunPython.noop),
    ]
