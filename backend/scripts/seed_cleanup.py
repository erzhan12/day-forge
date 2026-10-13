"""Opt-in cleanup for schedules created by Playwright smoke scripts."""

import json

from scripts import _required, _user
from scripts.seed_schedule import _clear_schedules


def main() -> None:
    user = _user()
    dates = json.loads(_required("SEED_DATES_JSON"))
    cleared = _clear_schedules(user, dates)
    print("cleanup cleared schedules:", cleared)


if __name__ == "__main__":
    main()
