"""Calendar-day boundaries and floating times in a saved user timezone."""

import datetime
from datetime import date

from schedules.window import resolve_time_zone


def local_date_to_utc(value: date, time_zone: str) -> datetime.datetime:
    """Interpret a date as midnight in the user's zone, then convert to UTC."""
    local = datetime.datetime.combine(
        value, datetime.time.min, tzinfo=resolve_time_zone(time_zone)
    )
    return local.astimezone(datetime.UTC)


def local_day_bounds_utc(
    target_date: date, time_zone: str
) -> tuple[datetime.datetime, datetime.datetime]:
    """Return the UTC instants bounding a user's local calendar day.

    Construct both local midnights independently. Adding 24 hours to a UTC
    boundary would miss or include an hour when the local clock changes.
    """
    return (
        local_date_to_utc(target_date, time_zone),
        local_date_to_utc(target_date + datetime.timedelta(days=1), time_zone),
    )


def floating_datetime_to_utc(value: datetime.datetime, time_zone: str) -> datetime.datetime:
    """Treat a timezone-less calendar time as wall time in the user's zone.

    An ambiguous repeated hour keeps Python's ``fold`` flag. Calendar values
    without that flag select the first occurrence (``fold=0``).
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=resolve_time_zone(time_zone))
    return value.astimezone(datetime.UTC)
