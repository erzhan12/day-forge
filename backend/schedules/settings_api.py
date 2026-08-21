"""JSON endpoint for the coupled per-user schedule window."""
import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.http import reject_oversized_body
from schedules.models import UserScheduleSettings
from schedules.window import get_schedule_window, validate_window


def _settings_response(payload: dict, *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET", "PATCH"])
def schedule_settings(request):
    if request.method == "GET":
        window = get_schedule_window(request.user)
        return _settings_response({"day_start": window.start_str, "day_end": window.end_str})

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
    missing = {
        field: f"{field} is required."
        for field in ("day_start", "day_end")
        if field not in data
    }
    if missing:
        return _settings_response({"errors": missing}, status=400)
    window, errors = validate_window(data["day_start"], data["day_end"])
    if errors:
        return _settings_response({"errors": errors}, status=400)
    assert window is not None
    # Create straight into the target window via ``defaults`` so a first-time
    # PATCH never persists the 06:00/23:00 model defaults in a separate write
    # that a concurrent reader could observe between the two saves.
    settings, created = UserScheduleSettings.objects.get_or_create(
        user=request.user,
        defaults={"day_start": window.day_start, "day_end": window.day_end},
    )
    if not created:
        settings.day_start = window.day_start
        settings.day_end = window.day_end
        settings.save(update_fields=["day_start", "day_end", "updated_at"])
    return _settings_response({"day_start": window.start_str, "day_end": window.end_str})
