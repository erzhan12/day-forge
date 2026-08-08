"""Perform separately timed template mutations for Playwright scenarios."""

import json

from schedules.models import Schedule
from templates_mgr.models import Template

from scripts import _required, _user


def main() -> None:
    mode = _required("SEED_MODE")
    user = _user()
    template = json.loads(_required("SEED_TEMPLATE_JSON"))
    if mode == "template_seed_initial":
        Template.objects.filter(user=user).delete()
        Template.objects.create(user=user, **template)
        dates = json.loads(_required("SEED_DATES_JSON"))
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
