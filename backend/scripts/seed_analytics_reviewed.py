"""Seed the reviewed analytics scenario, including its frozen review."""

import datetime
import json

from analytics.services import freeze_review_snapshot
from schedules.models import Schedule
from schedules.mutations import execute_schedule_maintenance, run_user_maintenance

from scripts import _required, _user
from scripts.seed_schedule import _replace_blocks_locked


def main() -> None:
    user = _user()

    def seed(_user):
        schedule, _ = Schedule.objects.get_or_create(
            user=user, date=datetime.date.fromisoformat(_required("SEED_DATE"))
        )

        def replace(context):
            _replace_blocks_locked(context.schedule, json.loads(_required("SEED_BLOCKS_JSON")))
            context.schedule.status = Schedule.Status.REVIEWED
            context.schedule.save(update_fields=["status"])

        result = execute_schedule_maintenance(user.pk, schedule.pk, replace)
        freeze_review_snapshot(result.schedule, revision=result.schedule.revision)
        return result.schedule

    schedule = run_user_maintenance(user.pk, seed)
    print("seeded schedule", schedule.id, "blocks", schedule.time_blocks.count())


if __name__ == "__main__":
    main()
