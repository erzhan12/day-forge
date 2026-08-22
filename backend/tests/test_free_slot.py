import datetime

from ai.free_slot import find_slot
from schedules.validators import validate_five_minute_granularity
from schedules.window import ScheduleWindow


def t(value: str) -> datetime.time:
    return datetime.time.fromisoformat(value)


WINDOW = ScheduleWindow(t("06:00"), t("23:00"))


def test_finds_nearest_later_slot_on_the_grid():
    suggestion = find_slot(t("16:00"), t("17:00"), "later", WINDOW, [(t("16:00"), t("17:30"))])
    assert suggestion.start_time == t("17:30") and suggestion.end_time == t("18:30")
    validate_five_minute_granularity(suggestion.start_time)
    validate_five_minute_granularity(suggestion.end_time)


def test_exact_requires_a_direction_and_invalid_duration_has_no_proposal():
    assert find_slot(t("16:00"), t("17:00"), "exact", WINDOW, []).direction_required
    assert find_slot(t("16:05"), t("16:03"), "later", WINDOW, []) is None


def test_later_from_desired_start_below_window_returns_in_window_slot():
    # Desired start (05:00) is BELOW the window start (06:00); the candidate
    # must be clamped up into the window instead of returning None.
    suggestion = find_slot(t("05:00"), t("05:30"), "later", WINDOW, [])
    assert suggestion is not None
    assert suggestion.start_time == t("06:00")
    assert suggestion.end_time == t("06:30")


def test_earlier_from_overrunning_start_returns_in_window_slot():
    # Desired interval 22:45-23:15 overruns window end (23:00); the earlier
    # candidate must be clamped down so the first interval fits.
    suggestion = find_slot(t("22:45"), t("23:15"), "earlier", WINDOW, [])
    assert suggestion is not None
    assert suggestion.end_time <= t("23:00")
    # Nearest in-window earlier slot: max start = 22:30 for a 30-min block.
    assert suggestion.start_time == t("22:30")
    assert suggestion.end_time == t("23:00")


def test_earlier_proposed_start_is_before_desired_start():
    # Monotonicity: an earlier proposal never starts at/after the desired
    # start when the desired interval itself overruns the window.
    desired_start = t("22:50")
    suggestion = find_slot(desired_start, t("23:20"), "earlier", WINDOW, [])
    assert suggestion is not None
    assert suggestion.start_time < desired_start


def test_fully_packed_window_returns_none():
    # One occupied interval spanning the entire window leaves no slot.
    suggestion = find_slot(
        t("09:00"), t("10:00"), "later", WINDOW, [(t("06:00"), t("23:00"))]
    )
    assert suggestion is None


def test_directional_monotonicity_both_directions():
    # ``later`` never returns a slot before the desired start.
    later = find_slot(t("08:00"), t("09:00"), "later", WINDOW, [(t("08:00"), t("10:30"))])
    assert later is not None
    assert later.start_time >= t("08:00")
    # ``earlier`` never returns a slot after the desired start.
    earlier = find_slot(
        t("14:00"), t("15:00"), "earlier", WINDOW, [(t("12:30"), t("15:00"))]
    )
    assert earlier is not None
    assert earlier.start_time <= t("14:00")
