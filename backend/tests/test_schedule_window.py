"""Pure unit tests for the ``ScheduleWindow`` value object (feature 0053, Slice 1).

No Django ORM: ``DEFAULT_WINDOW``, ``validate_window``, and ``clamp_boundary`` are
all pure functions/constants operating on ``datetime.time`` values. The stateful
``get_schedule_window`` lookup is covered separately in the model test suite.
"""
import datetime

from schedules.window import (
    DEFAULT_DAY_END,
    DEFAULT_DAY_START,
    DEFAULT_WINDOW,
    ScheduleWindow,
    check_time_on_grid,
    clamp_boundary,
    validate_window,
)

# --- DEFAULT_WINDOW ---------------------------------------------------------


def test_default_window_bounds():
    assert DEFAULT_WINDOW.day_start == datetime.time(6, 0)
    assert DEFAULT_WINDOW.day_end == datetime.time(23, 0)
    assert DEFAULT_WINDOW.day_start == DEFAULT_DAY_START
    assert DEFAULT_WINDOW.day_end == DEFAULT_DAY_END


def test_default_window_minutes():
    # 06:00 == 360 minutes since midnight; 23:00 == 1380.
    assert DEFAULT_WINDOW.start_minutes == 360
    assert DEFAULT_WINDOW.end_minutes == 1380


def test_default_window_str_accessors():
    assert DEFAULT_WINDOW.start_str == "06:00"
    assert DEFAULT_WINDOW.end_str == "23:00"


# --- validate_window: happy path --------------------------------------------


def test_validate_window_accepts_default_pair():
    window, errors = validate_window("06:00", "23:00")
    assert errors is None
    assert window == ScheduleWindow(datetime.time(6, 0), datetime.time(23, 0))
    assert window.start_minutes == 360
    assert window.end_minutes == 1380


# --- validate_window: rejections --------------------------------------------


def test_validate_window_rejects_non_hhmm():
    window, errors = validate_window("6am", "23:00")
    assert window is None
    assert errors == {"day_start": "Use HH:MM format."}


def test_validate_window_rejects_non_string():
    window, errors = validate_window(600, "23:00")
    assert window is None
    assert errors == {"day_start": "Must be an HH:MM string."}


def test_validate_window_rejects_non_canonical_single_digit_minute():
    # strptime alone accepts "6:0"; the strict HH:MM guard must reject it.
    window, errors = validate_window("6:0", "23:00")
    assert window is None
    assert errors == {"day_start": "Use HH:MM format."}


def test_validate_window_rejects_non_canonical_unpadded_minute():
    # "06:5" (single-digit minute) is off the canonical HH:MM contract.
    window, errors = validate_window("06:00", "06:5")
    assert window is None
    assert errors == {"day_end": "Use HH:MM format."}


def test_validate_window_rejects_off_grid():
    # 06:03 is not aligned to the 5-minute grid.
    window, errors = validate_window("06:03", "23:00")
    assert window is None
    assert errors == {"day_start": "Must align to 5-minute granularity."}


def test_validate_window_rejects_off_grid_on_end():
    window, errors = validate_window("06:00", "23:03")
    assert window is None
    assert errors == {"day_end": "Must align to 5-minute granularity."}


def test_validate_window_rejects_start_equals_end():
    window, errors = validate_window("06:00", "06:00")
    assert window is None
    # NOTE: diverges from plan — the impl couples the pair in one `start >= end`
    # check that always keys the error to `day_end` (not a separate `start == end`
    # vs `start > end` distinction).
    assert errors == {
        "day_end": "Must be later than day_start; overnight windows are not supported."
    }


def test_validate_window_rejects_start_after_end():
    window, errors = validate_window("23:00", "06:00")
    assert window is None
    assert errors == {
        "day_end": "Must be later than day_start; overnight windows are not supported."
    }


def test_validate_window_rejects_overnight():
    # An overnight window (20:00 -> 04:00) is a same-day start > end, so it is
    # rejected by the same coupled ordering check.
    window, errors = validate_window("20:00", "04:00")
    assert window is None
    assert errors == {
        "day_end": "Must be later than day_start; overnight windows are not supported."
    }


# --- clamp_boundary ---------------------------------------------------------

WINDOW = ScheduleWindow(datetime.time(6, 0), datetime.time(23, 0))


def test_clamp_boundary_both_flags_partial_cross_clamps_to_boundary():
    # Interval crosses both boundaries partially; both flags set -> clamp both.
    result = clamp_boundary(
        datetime.time(5, 0),
        datetime.time(23, 30),
        WINDOW,
        clamp_start=True,
        clamp_end=True,
    )
    assert result == (datetime.time(6, 0), datetime.time(23, 0))


def test_clamp_boundary_fully_outside_returns_none():
    # Wholly before the window; both flags set -> empty after clamp -> None.
    result = clamp_boundary(
        datetime.time(4, 0),
        datetime.time(5, 0),
        WINDOW,
        clamp_start=True,
        clamp_end=True,
    )
    assert result is None


def test_clamp_boundary_fully_inside_unchanged():
    result = clamp_boundary(
        datetime.time(9, 0),
        datetime.time(10, 0),
        WINDOW,
        clamp_start=True,
        clamp_end=True,
    )
    assert result == (datetime.time(9, 0), datetime.time(10, 0))


def test_clamp_boundary_single_start_flag_leaves_end_untouched():
    # Only the start boundary is flagged: start clamps to 06:00, the (legacy
    # out-of-window) end stays exactly as supplied.
    result = clamp_boundary(
        datetime.time(5, 0),
        datetime.time(23, 30),
        WINDOW,
        clamp_start=True,
        clamp_end=False,
    )
    assert result == (datetime.time(6, 0), datetime.time(23, 30))


def test_clamp_boundary_single_end_flag_leaves_start_untouched():
    # Only the end boundary is flagged: end clamps to 23:00, the legacy
    # out-of-window start (05:00) is preserved, not rewritten to 06:00.
    result = clamp_boundary(
        datetime.time(5, 0),
        datetime.time(23, 30),
        WINDOW,
        clamp_start=False,
        clamp_end=True,
    )
    assert result == (datetime.time(5, 0), datetime.time(23, 0))


def test_clamp_boundary_case_b_start_past_day_end_returns_none():
    # A flagged start that lands entirely past the opposite bound (start > day_end)
    # returns None rather than clamping toward the window from the near side.
    result = clamp_boundary(
        datetime.time(23, 35),
        datetime.time(23, 50),
        WINDOW,
        clamp_start=True,
        clamp_end=False,
    )
    assert result is None


def test_clamp_boundary_case_b_end_before_day_start_returns_none():
    # A flagged end before day_start (end < day_start) returns None.
    result = clamp_boundary(
        datetime.time(4, 0),
        datetime.time(5, 0),
        WINDOW,
        clamp_start=False,
        clamp_end=True,
    )
    assert result is None


# --- check_time_on_grid -----------------------------------------------------


def test_check_time_on_grid_accepts_clean_grid_time():
    assert check_time_on_grid(datetime.time(6, 0)) is None
    assert check_time_on_grid(datetime.time(22, 5)) is None


def test_check_time_on_grid_rejects_off_grid_minute():
    assert check_time_on_grid(datetime.time(6, 3)) == "Must align to 5-minute granularity."


def test_check_time_on_grid_rejects_seconds():
    # A grid-aligned minute carrying non-zero seconds is rejected: HH:MM
    # serialization would silently truncate the value.
    assert check_time_on_grid(datetime.time(6, 0, 30)) == "Must not include seconds."


def test_check_time_on_grid_rejects_microseconds():
    assert check_time_on_grid(datetime.time(6, 0, 0, 1)) == "Must not include seconds."
