from django.core.exceptions import ValidationError


def validate_five_minute_granularity(value):
    if value.minute % 5 != 0:
        raise ValidationError(
            f"Time must be in 5-minute increments (got :{value.minute:02d})."
        )
    if value.second != 0:
        raise ValidationError("Seconds must be zero.")
