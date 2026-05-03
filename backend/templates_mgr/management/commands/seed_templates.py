from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from templates_mgr.models import Rule, Template

WEEKDAY_BLOCKS = [
    {"title": "Morning routine", "start_time": "07:00", "end_time": "07:30", "category": "health"},
    {"title": "Deep work", "start_time": "09:00", "end_time": "12:00", "category": "work"},
    {"title": "Lunch", "start_time": "12:00", "end_time": "13:00", "category": "other"},
    {"title": "Meetings", "start_time": "13:00", "end_time": "15:00", "category": "work"},
    {"title": "Deep work", "start_time": "15:00", "end_time": "17:00", "category": "work"},
    {"title": "Gym", "start_time": "17:30", "end_time": "18:30", "category": "health"},
]

WEEKEND_BLOCKS = [
    {"title": "Morning routine", "start_time": "08:00", "end_time": "09:00", "category": "health"},
    {
        "title": "Personal project",
        "start_time": "10:00",
        "end_time": "12:00",
        "category": "personal",
    },
    {"title": "Lunch", "start_time": "12:00", "end_time": "13:00", "category": "other"},
    {"title": "Free time", "start_time": "14:00", "end_time": "17:00", "category": "personal"},
]

DEFAULT_RULES = [
    ("Never schedule meetings before 9:00 AM", 10),
    ("Lunch must be between 12:00 and 14:00", 5),
]


class Command(BaseCommand):
    help = (
        "Seed default weekday/weekend templates and starter rules for a "
        "specific user. The --user argument is required — there is no "
        "fallback to 'first superuser' because templates and rules are "
        "per-user, and silently binding seed data to an arbitrary user is "
        "ambiguous in a multi-user world."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            required=True,
            help="Username to scope the seeded templates and rules to.",
        )

    def handle(self, *args, **options):
        username = options["user"]
        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(username=username)
        except UserModel.DoesNotExist as e:
            raise CommandError(f"User {username!r} does not exist.") from e

        created = 0

        for name, tpl_type, blocks in [
            ("Default Weekday", Template.Type.WEEKDAY, WEEKDAY_BLOCKS),
            ("Default Weekend", Template.Type.WEEKEND, WEEKEND_BLOCKS),
        ]:
            if not Template.objects.filter(user=user, type=tpl_type).exists():
                Template.objects.create(
                    user=user, name=name, type=tpl_type, blocks=blocks
                )
                self.stdout.write(f"Created: {name} template for {username}")
                created += 1
            else:
                self.stdout.write(
                    f"Skipped: {name} template (already exists for {username})"
                )

        for text, priority in DEFAULT_RULES:
            if not Rule.objects.filter(user=user, text=text).exists():
                Rule.objects.create(user=user, text=text, priority=priority)
                self.stdout.write(f"Created rule for {username}: {text}")
                created += 1
            else:
                self.stdout.write(
                    f"Skipped rule for {username}: {text} (already exists)"
                )

        self.stdout.write(
            self.style.SUCCESS(f"Done. {created} item(s) created for {username}.")
        )
