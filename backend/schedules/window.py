"""Canonical per-user working-day window policy for schedules.

Do not use the default constants as runtime policy: resolve a user's window
with :func:`get_schedule_window` at each HTTP/AI enforcement boundary.
"""

import datetime
import re
from dataclasses import dataclass

from schedules.models import UserScheduleSettings

DEFAULT_DAY_START = datetime.time(6, 0)
DEFAULT_DAY_END = datetime.time(23, 0)

# Strict two-digit, zero-padded 24-hour HH:MM. ``datetime.strptime`` alone
# leniently accepts "6:0" / "06:5", which violates the HH:MM API contract, so
# guard with this pattern before parsing.
_HHMM_RE = re.compile(r"^\d{2}:\d{2}$")


def check_time_on_grid(value: datetime.time) -> str | None:
    """Return an error message if ``value`` is not a clean 5-minute-grid time.

    A ``datetime.time`` carrying non-zero seconds/microseconds (e.g.
    ``time(6, 0, 30)``) is rejected: HH:MM serialization truncates it, but
    downstream comparisons use the full value, so an off-second value breaks
    the alignment invariant. Also enforces ``minute % 5 == 0``. Returns
    ``None`` when the value is a clean grid time. Shared by ``validate_window``
    (string surface) and ``UserScheduleSettings.clean`` (model surface) so the
    grid/alignment rule lives in exactly one place.
    """
    if value.second or value.microsecond:
        return "Must not include seconds."
    if value.minute % 5:
        return "Must align to 5-minute granularity."
    return None


@dataclass(frozen=True)
class ScheduleWindow:
    day_start: datetime.time
    day_end: datetime.time

    @property
    def start_str(self) -> str:
        return self.day_start.strftime("%H:%M")

    @property
    def end_str(self) -> str:
        return self.day_end.strftime("%H:%M")

    @property
    def start_minutes(self) -> int:
        return self.day_start.hour * 60 + self.day_start.minute

    @property
    def end_minutes(self) -> int:
        return self.day_end.hour * 60 + self.day_end.minute


DEFAULT_WINDOW = ScheduleWindow(DEFAULT_DAY_START, DEFAULT_DAY_END)


def validate_window(day_start_str, day_end_str) -> tuple[ScheduleWindow | None, dict | None]:
    """Parse and validate a coupled ``HH:MM`` day-window pair."""
    errors: dict[str, str] = {}
    parsed: dict[str, datetime.time] = {}
    for field, raw in (("day_start", day_start_str), ("day_end", day_end_str)):
        if not isinstance(raw, str):
            errors[field] = "Must be an HH:MM string."
            continue
        # ``strptime`` alone accepts "6:0"/"06:5"; require strict zero-padded
        # two-digit HH:MM first so a non-canonical value is rejected.
        if not _HHMM_RE.match(raw):
            errors[field] = "Use HH:MM format."
            continue
        try:
            value = datetime.datetime.strptime(raw, "%H:%M").time()
        except ValueError:
            errors[field] = "Use HH:MM format."
            continue
        grid_error = check_time_on_grid(value)
        if grid_error:
            errors[field] = grid_error
            continue
        parsed[field] = value
    if errors:
        return None, errors
    if parsed["day_start"] >= parsed["day_end"]:
        errors["day_end"] = "Must be later than day_start; overnight windows are not supported."
        return None, errors
    return ScheduleWindow(parsed["day_start"], parsed["day_end"]), None


def get_schedule_window(user) -> ScheduleWindow:
    """Return a user's frozen window DTO.

    This is a single-user, request-scoped lookup. Do not call it in a loop
    over users: bulk callers should query ``UserScheduleSettings`` directly.
    """
    settings, _ = UserScheduleSettings.objects.get_or_create(
        user=user, defaults={"day_start": DEFAULT_DAY_START, "day_end": DEFAULT_DAY_END}
    )
    return ScheduleWindow(settings.day_start, settings.day_end)


def clamp_boundary(
    start: datetime.time,
    end: datetime.time,
    window: ScheduleWindow,
    *,
    clamp_start: bool,
    clamp_end: bool,
) -> tuple[datetime.time, datetime.time] | None:
    """Clamp only requested boundaries, returning ``None`` if fully outside."""
    if clamp_start:
        if start > window.day_end:
            return None
        start = max(start, window.day_start)
    if clamp_end:
        if end < window.day_start:
            return None
        end = min(end, window.day_end)
    if start >= end:
        return None
    return start, end
