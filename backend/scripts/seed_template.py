"""Perform separately timed template mutations for Playwright scenarios."""

import json
import os

from django.contrib.auth.models import User
from schedules.models import Schedule
from templates_mgr.models import Template


def main() -> None:
    mode = os.environ["SEED_MODE"]
    user = User.objects.get(username=os.environ["SEED_USERNAME"])
    template = json.loads(os.environ["SEED_TEMPLATE_JSON"])
    if mode == "template_seed_initial":
        Template.objects.filter(user=user).delete()
        Template.objects.create(user=user, **template)
        dates = json.loads(os.environ["SEED_DATES_JSON"])
        for value in dates:
            schedule, _ = Schedule.objects.update_or_create(
                user=user, date=value, defaults={"status": "draft"}
            )
            schedule.time_blocks.all().delete()
        print("seeded")
    elif mode == "template_delete":
        Template.objects.filter(user=user, type=template["type"]).delete()
        print("deleted")
    elif mode == "template_create":
        Template.objects.create(user=user, **template)
        print("re-created")
    else:
        raise RuntimeError(f"Unknown SEED_MODE: {mode}")


if __name__ == "__main__":
    main()
