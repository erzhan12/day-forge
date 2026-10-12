"""Time parsing and schedule interval checks without HTTP or model dependencies."""

import datetime


class TimeValidationError(ValueError):
    """A time validation failure with the API field and message to report."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(message)


def parse_time(value):
    """Parse an HH:MM string into a time."""
    return datetime.datetime.strptime(value, "%H:%M").time()


def parse_time_field(field_name, value, block_id=None):
    """Parse a field and attach its name and optional block ID to format errors."""
    try:
        return parse_time(value)
    except (ValueError, TypeError) as error:
        suffix = f" for block {block_id}" if block_id is not None else ""
        raise TimeValidationError(field_name, f"Invalid time format{suffix}. Use HH:MM.") from error


def grid_components(value: datetime.time) -> tuple[bool, bool]:
    """Return (off-minute-grid, sub-minute precision) for both time surfaces."""
    return value.minute % 5 != 0, value.second != 0 or value.microsecond != 0


def validate_five_minute_granularity(value):
    off_minute_grid, sub_minute = grid_components(value)
    if off_minute_grid:
        raise TimeValidationError(
            "time", f"Time must be in 5-minute increments (got :{value.minute:02d})."
        )
    if sub_minute:
        raise TimeValidationError("time", "Seconds must be zero.")


def validate_time_range(start, end, block_id=None):
    """Require an interval with its start before its end."""
    if start >= end:
        suffix = f" for block {block_id}" if block_id is not None else ""
        raise TimeValidationError("time", f"Start time must be before end time{suffix}.")


def validate_block_times(start_str, end_str, block_id=None, *, enforce_granularity=True):
    """Parse both bounds, check the optional grid, then check their order."""
    start = parse_time_field("start_time", start_str, block_id=block_id)
    end = parse_time_field("end_time", end_str, block_id=block_id)
    if enforce_granularity:
        validate_five_minute_granularity(start)
        validate_five_minute_granularity(end)
    validate_time_range(start, end, block_id=block_id)
    return start, end


def times_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Return whether two half-open intervals [start, end) overlap."""
    return a_start < b_end and a_end > b_start
