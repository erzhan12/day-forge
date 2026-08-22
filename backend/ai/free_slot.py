"""Deterministic free-slot search used by the chat mutation planner."""

from __future__ import annotations

import datetime
from collections.abc import Iterable

from schedules.http import times_overlap
from schedules.window import ScheduleWindow

# Keep aligned with schedules.validators.validate_five_minute_granularity.
GRID_MINUTES = 5


def _minutes(value: datetime.time) -> int:
    return value.hour * 60 + value.minute


def _time(value: int) -> datetime.time:
    hour, minute = divmod(value, 60)
    return datetime.time(hour, minute)


def find_slot(
    desired_start: datetime.time,
    desired_end: datetime.time,
    direction: str,
    window: ScheduleWindow,
    occupied_intervals: Iterable[tuple[datetime.time, datetime.time]],
):
    """Return a SlotSuggestion, an exact-direction sentinel, or None.

    The import is deliberately local: ``SlotSuggestion`` is the planner's
    public result type and the planner imports this module only after its
    dataclasses have loaded.
    """
    from ai.mutation_planner import SlotSuggestion

    start = _minutes(desired_start)
    end = _minutes(desired_end)
    duration = end - start
    if duration <= 0 or duration % GRID_MINUTES:
        return None
    if direction == "exact":
        return SlotSuggestion(direction_required=True)
    if direction not in {"later", "earlier"}:
        return None

    occupied = list(occupied_intervals)
    if direction == "later":
        candidate = ((start + GRID_MINUTES - 1) // GRID_MINUTES) * GRID_MINUTES
        # Clamp the starting candidate up into the window; the loop guard is
        # false on entry otherwise and returns None even when a later slot
        # exists (window bounds are grid-aligned).
        candidate = max(candidate, window.start_minutes)
        step = GRID_MINUTES
    else:
        candidate = (start // GRID_MINUTES) * GRID_MINUTES
        # Clamp the starting candidate down so the first interval fits inside
        # the window end; otherwise the guard is false on entry.
        max_start = ((window.end_minutes - duration) // GRID_MINUTES) * GRID_MINUTES
        candidate = min(candidate, max_start)
        step = -GRID_MINUTES

    while window.start_minutes <= candidate and candidate + duration <= window.end_minutes:
        candidate_start, candidate_end = _time(candidate), _time(candidate + duration)
        if not any(
            times_overlap(candidate_start, candidate_end, occupied_start, occupied_end)
            for occupied_start, occupied_end in occupied
        ):
            return SlotSuggestion(candidate_start, candidate_end, direction)
        candidate += step
    return None
