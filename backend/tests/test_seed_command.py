import pytest
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from templates_mgr.models import Rule, Template


@pytest.fixture
def seed_user(db):
    return User.objects.create_user(username="seedme", password="x")


@pytest.mark.django_db
class TestSeedTemplates:
    def test_creates_templates_and_rules(self, seed_user):
        call_command("seed_templates", "--user", "seedme")
        assert Template.objects.filter(
            user=seed_user, type="weekday"
        ).exists()
        assert Template.objects.filter(
            user=seed_user, type="weekend"
        ).exists()
        assert Rule.objects.filter(user=seed_user).count() == 2

    def test_weekday_template_blocks(self, seed_user):
        call_command("seed_templates", "--user", "seedme")
        tpl = Template.objects.get(user=seed_user, type="weekday")
        assert len(tpl.blocks) == 6
        assert all("title" in b and "start_time" in b for b in tpl.blocks)

    def test_idempotent(self, seed_user):
        call_command("seed_templates", "--user", "seedme")
        call_command("seed_templates", "--user", "seedme")
        assert Template.objects.filter(user=seed_user).count() == 2
        assert Rule.objects.filter(user=seed_user).count() == 2

    def test_requires_user_arg(self, db):
        with pytest.raises(CommandError):
            call_command("seed_templates")

    def test_unknown_user(self, db):
        with pytest.raises(CommandError):
            call_command("seed_templates", "--user", "nope")

    def test_per_user_isolation(self, seed_user):
        other = User.objects.create_user(username="other-seed", password="x")
        call_command("seed_templates", "--user", "seedme")
        call_command("seed_templates", "--user", "other-seed")
        assert Template.objects.filter(user=seed_user).count() == 2
        assert Template.objects.filter(user=other).count() == 2
