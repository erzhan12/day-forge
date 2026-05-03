from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0003_aiinteraction_success"),
    ]

    operations = [
        migrations.AddField(
            model_name="aiinteraction",
            name="kind",
            field=models.CharField(
                choices=[("command", "Command"), ("draft", "Draft")],
                default="command",
                max_length=10,
            ),
        ),
    ]
