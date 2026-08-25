from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("calendar_sync", "0003_travelrule_calendar_name_alter_travelrule_keyword")]
    operations = [migrations.AlterField(model_name="travelrule", name="category", field=models.CharField(blank=True, default="", max_length=32))]
