import datetime
import json

import pytest
from django.core.exceptions import ValidationError
from schedules import http, time_validation
from schedules.validators import validate_five_minute_granularity
from schedules.window import check_time_on_grid


@pytest.mark.parametrize(
    ("start", "end", "field", "message"),
    [
        ("bad", "bad", "start_time", "Invalid time format for block 7. Use HH:MM."),
        ("09:01", "bad", "end_time", "Invalid time format for block 7. Use HH:MM."),
        ("10:01", "09:02", "time", "Time must be in 5-minute increments (got :01)."),
        ("10:00", "09:02", "time", "Time must be in 5-minute increments (got :02)."),
        ("10:00", "09:00", "time", "Start time must be before end time for block 7."),
        ("10:00", "10:00", "time", "Start time must be before end time for block 7."),
    ],
)
def test_block_time_failure_order_and_http_mapping(start, end, field, message):
    with pytest.raises(time_validation.TimeValidationError) as failure:
        time_validation.validate_block_times(start, end, block_id=7)
    assert failure.value.field == field
    assert failure.value.message == message

    parsed_start, parsed_end, response = http.validate_block_times(start, end, block_id=7)
    assert parsed_start is None
    assert parsed_end is None
    assert response.status_code == 400
    assert json.loads(response.content) == {"errors": {field: message}}


def test_block_time_validation_can_restore_off_grid_values():
    expected = datetime.time(9, 1), datetime.time(10, 2)
    assert (
        time_validation.validate_block_times("09:01", "10:02", enforce_granularity=False)
        == expected
    )
    assert http.validate_block_times("09:01", "10:02", enforce_granularity=False) == (
        *expected,
        None,
    )
    with pytest.raises(time_validation.TimeValidationError, match="Start time"):
        time_validation.validate_block_times("10:02", "09:01", enforce_granularity=False)
    with pytest.raises(time_validation.TimeValidationError, match="Invalid time format"):
        time_validation.validate_block_times("invalid", "10:02", enforce_granularity=False)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (datetime.time(9, 1, 1), "Time must be in 5-minute increments (got :01)."),
        (datetime.time(9, 0, 1), "Seconds must be zero."),
        (datetime.time(9, 0, 0, 1), "Seconds must be zero."),
    ],
)
def test_grid_validation_preserves_django_model_errors(value, message):
    with pytest.raises(time_validation.TimeValidationError) as domain_failure:
        time_validation.validate_five_minute_granularity(value)
    assert domain_failure.value.field == "time"
    assert domain_failure.value.message == message

    with pytest.raises(ValidationError) as model_failure:
        validate_five_minute_granularity(value)
    assert model_failure.value.message == message


def test_window_and_block_grid_share_microsecond_classification():
    assert check_time_on_grid(datetime.time(9, 0, 0, 1)) == "Must not include seconds."
    assert check_time_on_grid(datetime.time(9, 1, 1)) == "Must not include seconds."
    assert check_time_on_grid(datetime.time(9, 1)) == "Must align to 5-minute granularity."


def test_parse_time_preserves_existing_unpadded_format():
    assert time_validation.parse_time("9:5") == datetime.time(9, 5)
    assert time_validation.validate_block_times("9:5", "10:0") == (
        datetime.time(9, 5),
        datetime.time(10),
    )


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("09:30", "10:30", True),
        ("10:00", "11:00", False),
        ("08:00", "09:00", False),
    ],
)
def test_overlap_uses_half_open_intervals(start, end, expected):
    assert (
        time_validation.times_overlap(
            datetime.time(9),
            datetime.time(10),
            time_validation.parse_time(start),
            time_validation.parse_time(end),
        )
        is expected
    )
