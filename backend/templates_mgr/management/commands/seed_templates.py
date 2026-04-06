from django.core.management.base import BaseCommand

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
    help = "Seed default weekday/weekend templates and starter rules"

    def handle(self, *args, **options):
        created = 0

        for name, tpl_type, blocks in [
            ("Default Weekday", Template.Type.WEEKDAY, WEEKDAY_BLOCKS),
            ("Default Weekend", Template.Type.WEEKEND, WEEKEND_BLOCKS),
        ]:
            if not Template.objects.filter(name=name).exists():
                Template.objects.create(name=name, type=tpl_type, blocks=blocks)
                self.stdout.write(f"Created: {name} template")
                created += 1
            else:
                self.stdout.write(f"Skipped: {name} template (already exists)")

        for text, priority in DEFAULT_RULES:
            if not Rule.objects.filter(text=text).exists():
                Rule.objects.create(text=text, priority=priority)
                self.stdout.write(f"Created rule: {text}")
                created += 1
            else:
                self.stdout.write(f"Skipped rule: {text} (already exists)")

        self.stdout.write(self.style.SUCCESS(f"Done. {created} item(s) created."))
