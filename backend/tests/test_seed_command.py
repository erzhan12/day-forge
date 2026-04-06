import pytest
from django.core.management import call_command
from templates_mgr.models import Rule, Template


@pytest.mark.django_db
class TestSeedTemplates:
    def test_creates_templates_and_rules(self):
        call_command("seed_templates")
        assert Template.objects.filter(name="Default Weekday", type="weekday").exists()
        assert Template.objects.filter(name="Default Weekend", type="weekend").exists()
        assert Rule.objects.count() == 2

    def test_weekday_template_blocks(self):
        call_command("seed_templates")
        tpl = Template.objects.get(name="Default Weekday")
        assert len(tpl.blocks) == 6
        assert all("title" in b and "start_time" in b for b in tpl.blocks)

    def test_idempotent(self):
        call_command("seed_templates")
        call_command("seed_templates")
        assert Template.objects.count() == 2
        assert Rule.objects.count() == 2
