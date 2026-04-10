import datetime
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.models import Schedule, TimeBlock

VALID_CATEGORIES = {c.value for c in TimeBlock.Category}


def _parse_time(value):
    """Parse 'HH:MM' string to datetime.time."""
    return datetime.datetime.strptime(value, "%H:%M").time()


def _block_to_dict(block):
    return {
        "id": block.id,
        "title": block.title,
        "start_time": block.start_time.strftime("%H:%M"),
        "end_time": block.end_time.strftime("%H:%M"),
        "category": block.category,
        "is_completed": block.is_completed,
        "sort_order": block.sort_order,
    }


@login_required
@require_http_methods(["POST"])
def create_block(request, date):
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return JsonResponse({"errors": {"date": "Invalid date format."}}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"errors": {"body": "Invalid JSON."}}, status=400)

    schedule, _ = Schedule.objects.get_or_create(user=request.user, date=parsed_date)

    for field in ("start_time", "end_time"):
        if field not in data:
            return JsonResponse(
                {"errors": {field: f"{field} is required."}}, status=400
            )

    try:
        start = _parse_time(data["start_time"])
    except ValueError:
        return JsonResponse(
            {"errors": {"start_time": "Invalid time format. Use HH:MM."}}, status=400
        )

    try:
        end = _parse_time(data["end_time"])
    except ValueError:
        return JsonResponse(
            {"errors": {"end_time": "Invalid time format. Use HH:MM."}}, status=400
        )

    title = data.get("title", "").strip()
    if not title:
        return JsonResponse(
            {"errors": {"title": "Title is required."}}, status=400
        )
    if len(title) > 255:
        return JsonResponse(
            {"errors": {"title": "Title too long (max 255 characters)."}}, status=400
        )

    category = data.get("category", "other")
    if category not in VALID_CATEGORIES:
        choices = ", ".join(sorted(VALID_CATEGORIES))
        return JsonResponse(
            {"errors": {"category": f"Invalid category. Choose from: {choices}."}},
            status=400,
        )

    if start >= end:
        return JsonResponse(
            {"errors": {"time": "Start time must be before end time."}}, status=400
        )

    # NOTE: On PostgreSQL, add .select_for_update() to prevent race conditions.
    # SQLite uses DB-level locking only; row-level locks are silently ignored.
    try:
        with transaction.atomic():
            overlap = TimeBlock.objects.filter(
                schedule=schedule,
                start_time__lt=end,
                end_time__gt=start,
            ).exists()
            if overlap:
                return JsonResponse(
                    {"errors": {"time": "This block overlaps with an existing block."}},
                    status=400,
                )
            block = TimeBlock(
                schedule=schedule,
                title=title,
                start_time=start,
                end_time=end,
                category=category,
            )
            block.full_clean()
            block.save()
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    return JsonResponse(_block_to_dict(block), status=201)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def block_detail(request, pk):
    try:
        block = TimeBlock.objects.select_related("schedule").get(pk=pk)
    except TimeBlock.DoesNotExist:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)

    if block.schedule.user != request.user:
        return JsonResponse({"errors": {"detail": "Forbidden."}}, status=403)

    if request.method == "DELETE":
        block.delete()
        return JsonResponse({"ok": True})

    # PATCH
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"errors": {"body": "Invalid JSON."}}, status=400)

    if "start_time" in data:
        try:
            block.start_time = _parse_time(data["start_time"])
        except ValueError:
            return JsonResponse(
                {"errors": {"start_time": "Invalid time format. Use HH:MM."}},
                status=400,
            )
    if "end_time" in data:
        try:
            block.end_time = _parse_time(data["end_time"])
        except ValueError:
            return JsonResponse(
                {"errors": {"end_time": "Invalid time format. Use HH:MM."}},
                status=400,
            )

    try:
        if "title" in data:
            if not isinstance(data["title"], str):
                return JsonResponse(
                    {"errors": {"title": "Title must be a string."}}, status=400
                )
            block.title = data["title"].strip()
            if not block.title:
                return JsonResponse(
                    {"errors": {"title": "Title cannot be empty."}}, status=400
                )
            if len(block.title) > 255:
                return JsonResponse(
                    {"errors": {"title": "Title too long (max 255 characters)."}}, status=400
                )
        if "is_completed" in data:
            if not isinstance(data["is_completed"], bool):
                return JsonResponse(
                    {"errors": {"is_completed": "is_completed must be a boolean."}},
                    status=400,
                )
            block.is_completed = data["is_completed"]
        if "category" in data:
            if data["category"] not in VALID_CATEGORIES:
                choices = ", ".join(sorted(VALID_CATEGORIES))
                return JsonResponse(
                    {"errors": {"category": f"Invalid category. Choose from: {choices}."}},
                    status=400,
                )
            block.category = data["category"]
        if "sort_order" in data:
            sort_order = data["sort_order"]
            if not isinstance(sort_order, int) or isinstance(sort_order, bool):
                return JsonResponse(
                    {"errors": {"sort_order": "sort_order must be an integer."}},
                    status=400,
                )
            if not (0 <= sort_order <= 10_000):
                return JsonResponse(
                    {"errors": {"sort_order": "sort_order must be between 0 and 10000."}},
                    status=400,
                )
            block.sort_order = sort_order
        if "start_time" in data or "end_time" in data:
            if block.start_time >= block.end_time:
                return JsonResponse(
                    {"errors": {"time": "Start time must be before end time."}},
                    status=400,
                )
            with transaction.atomic():
                overlap = TimeBlock.objects.filter(
                    schedule=block.schedule,
                    start_time__lt=block.end_time,
                    end_time__gt=block.start_time,
                ).exclude(pk=block.pk).exists()
                if overlap:
                    return JsonResponse(
                        {"errors": {"time": "This block overlaps with an existing block."}},
                        status=400,
                    )
                block.full_clean()
                block.save()
        else:
            block.full_clean()
            block.save()
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    return JsonResponse(_block_to_dict(block))
