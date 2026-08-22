from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai", "0005_alter_aiinteraction_kind")]

    operations = [
        migrations.AddField(
            model_name="aiinteraction",
            name="outcomes_json",
            field=models.JSONField(default=None, null=True),
        ),
    ]
