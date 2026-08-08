"""Opt-in cleanup for schedules created by Playwright smoke scripts."""

import json

from schedules.models import Schedule

from scripts import _required, _user


def main() -> None:
    user = _user()
    dates = json.loads(_required("SEED_DATES_JSON"))
    deleted, _ = Schedule.objects.filter(user=user, date__in=dates).delete()
    print("cleanup deleted rows:", deleted)


if __name__ == "__main__":
    main()
