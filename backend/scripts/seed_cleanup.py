"""Opt-in cleanup for schedules created by Playwright smoke scripts."""

import json
import os

from django.contrib.auth.models import User
from schedules.models import Schedule


def main() -> None:
    user = User.objects.get(username=os.environ["SEED_USERNAME"])
    dates = json.loads(os.environ["SEED_DATES_JSON"])
    deleted, _ = Schedule.objects.filter(user=user, date__in=dates).delete()
    print("cleanup deleted rows:", deleted)


if __name__ == "__main__":
    main()
