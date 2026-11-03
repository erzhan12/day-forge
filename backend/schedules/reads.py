"""Owner-scoped, read-snapshot schedule/day capture (feature 0088).

Extracted from ``schedules.views._read_schedule_page`` so a read-only caller
(the daily export API, and that view itself) can capture a day's schedule
and ordered blocks without reserving the SQLite writer or bootstrapping
first-use rows. Callers that need page bootstrap/policy reads keep owning
their own outer transaction and ``UPDATE User`` reservation; this helper
never takes one.
"""

from django.db import transaction

from schedules.models import Schedule


def read_schedule_day(user, date):
    """Return ``(schedule, blocks)`` for ``user``'s ``date``, or ``None`` if absent.

    Captures the schedule and its blocks (ordered by ``start_time``,
    ``sort_order``, ``id``) inside one read transaction/snapshot. Never
    creates rows and never reserves the SQLite writer.
    """
    with transaction.atomic():
        schedule = Schedule.objects.filter(user=user, date=date).first()
        if schedule is None:
            return None
        blocks = list(schedule.time_blocks.order_by("start_time", "sort_order", "id"))
        return schedule, blocks
