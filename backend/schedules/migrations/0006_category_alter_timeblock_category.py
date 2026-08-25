from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
from django.db.models.functions import Lower, Trim


class Migration(migrations.Migration):
    dependencies = [("schedules", "0005_userschedulesettings")]
    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slug", models.CharField(max_length=32)), ("label", models.CharField(max_length=64)),
                ("color_id", models.CharField(max_length=16)), ("sort_order", models.IntegerField(default=0)),
                ("is_sink", models.BooleanField(default=False)), ("is_new_block_default", models.BooleanField(default=False)),
                ("user", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="categories", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["sort_order", "id"]},
        ),
        migrations.AlterField(model_name="timeblock", name="category", field=models.CharField(default="other", max_length=32)),
        migrations.AddConstraint(model_name="category", constraint=models.UniqueConstraint(fields=("user", "slug"), name="unique_user_category_slug")),
        migrations.AddConstraint(model_name="category", constraint=models.UniqueConstraint(Lower(Trim("label")), "user", name="unique_user_category_label_ci")),
        migrations.AddConstraint(model_name="category", constraint=models.UniqueConstraint(condition=Q(is_sink=True), fields=("user",), name="one_sink_category_per_user")),
        migrations.AddConstraint(model_name="category", constraint=models.UniqueConstraint(condition=Q(is_new_block_default=True), fields=("user",), name="one_default_category_per_user")),
        migrations.AddConstraint(model_name="category", constraint=models.CheckConstraint(condition=Q(is_sink=False) | Q(slug="other"), name="sink_category_uses_other_slug")),
    ]
