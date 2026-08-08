"""Seed the reviewed analytics scenario, including its frozen review."""

import datetime
import json

from analytics.services import recompute_review_from_schedule
from schedules.models import Schedule

from scripts import _required, _user
from scripts.seed_schedule import _replace_blocks


def main() -> None:
    user = _user()
    schedule, _ = Schedule.objects.update_or_create(
        user=user,
        date=datetime.date.fromisoformat(_required("SEED_DATE")),
        defaults={"status": Schedule.Status.ACTIVE},
    )
    _replace_blocks(schedule, json.loads(_required("SEED_BLOCKS_JSON")))
    recompute_review_from_schedule(schedule)
    schedule.status = Schedule.Status.REVIEWED
    schedule.save(update_fields=["status"])
    print("seeded schedule", schedule.id, "blocks", schedule.time_blocks.count())


if __name__ == "__main__":
    main()
