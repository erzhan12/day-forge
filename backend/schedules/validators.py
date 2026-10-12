from django.core.exceptions import ValidationError

from schedules.time_validation import (
    TimeValidationError,
)
from schedules.time_validation import (
    validate_five_minute_granularity as validate_time_granularity,
)


def validate_five_minute_granularity(value):
    """Adapt the domain grid check to Django model validation."""
    try:
        validate_time_granularity(value)
    except TimeValidationError as error:
        raise ValidationError(error.message) from error
