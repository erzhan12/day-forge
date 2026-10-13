"""Perform separately timed template mutations for Playwright scenarios."""

import json

from schedules.mutations import run_user_maintenance
from templates_mgr.models import Template

from scripts import _required, _user
from scripts.seed_schedule import _upsert_schedule


def main() -> None:
    mode = _required("SEED_MODE")
    user = _user()
    template = json.loads(_required("SEED_TEMPLATE_JSON"))
    if mode == "template_seed_initial":
        def seed(_user):
            Template.objects.filter(user=user).delete()
            Template.objects.create(user=user, **template)
            dates = json.loads(_required("SEED_DATES_JSON"))
            for value in dates:
                _upsert_schedule(user, {"date": value, "status": "draft", "blocks": []})

        run_user_maintenance(user.pk, seed)
        print("seeded")
    elif mode == "template_delete":
        run_user_maintenance(
            user.pk,
            lambda _user: Template.objects.filter(user=user, type=template["type"]).delete(),
        )
        print("deleted")
    elif mode == "template_create":
        run_user_maintenance(user.pk, lambda _user: Template.objects.create(user=user, **template))
        print("re-created")
    else:
        raise RuntimeError(f"Unknown SEED_MODE: {mode}")


if __name__ == "__main__":
    main()
