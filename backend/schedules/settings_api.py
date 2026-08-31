"""JSON endpoint for the coupled per-user schedule window."""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.http import reject_oversized_body
from schedules.models import UserScheduleSettings
from schedules.window import get_schedule_settings, validate_time_zone, validate_window


def _settings_response(payload: dict, *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET", "PATCH"])
def schedule_settings(request):
    if request.method == "GET":
        schedule_settings = get_schedule_settings(request.user)
        return _settings_response(
            {
                "day_start": schedule_settings.window.start_str,
                "day_end": schedule_settings.window.end_str,
                "time_zone": schedule_settings.time_zone,
            }
        )

    oversized = reject_oversized_body(request)
    if oversized is not None:
        oversized["Cache-Control"] = "private, no-store"
        return oversized
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _settings_response({"errors": {"body": "Invalid JSON."}}, status=400)
    if not isinstance(data, dict):
        return _settings_response(
            {"errors": {"body": "Request body must be a JSON object."}}, status=400
        )
    has_start = "day_start" in data
    has_end = "day_end" in data
    has_time_zone = "time_zone" in data
    errors = {}
    if has_start != has_end or not (has_start or has_time_zone):
        for field in ("day_start", "day_end"):
            if field not in data:
                errors[field] = f"{field} is required."
    window = None
    if has_start and has_end:
        window, window_errors = validate_window(data["day_start"], data["day_end"])
        if window_errors:
            errors.update(window_errors)
    if has_time_zone:
        try:
            validate_time_zone(data["time_zone"])
        except ValidationError:
            errors["time_zone"] = "Must be a valid IANA time zone."
    if errors:
        return _settings_response({"errors": errors}, status=400)
    if has_start and window is None:
        # Unreachable today (validate_window returns either an error dict or a
        # window), but an assert would be stripped under `python -O`.
        return _settings_response({"errors": {"detail": "Internal validation error."}}, status=500)
    # Create straight into the target window via ``defaults`` so a first-time
    # PATCH never persists the 06:00/23:00 model defaults in a separate write
    # that a concurrent reader could observe between the two saves.
    defaults = {}
    if window is not None:
        defaults.update(day_start=window.day_start, day_end=window.day_end)
    if has_time_zone:
        defaults["time_zone"] = data["time_zone"]
    settings, created = UserScheduleSettings.objects.get_or_create(
        user=request.user, defaults=defaults
    )
    if not created:
        update_fields = []
        if window is not None:
            settings.day_start = window.day_start
            settings.day_end = window.day_end
            update_fields.extend(["day_start", "day_end"])
        if has_time_zone:
            settings.time_zone = data["time_zone"]
            update_fields.append("time_zone")
        settings.save(update_fields=[*update_fields, "updated_at"])
    return _settings_response(
        {
            "day_start": settings.day_start.strftime("%H:%M"),
            "day_end": settings.day_end.strftime("%H:%M"),
            "time_zone": settings.time_zone,
        }
    )
