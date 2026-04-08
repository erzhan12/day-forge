import datetime
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.models import Schedule, TimeBlock


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

    if start >= end:
        return JsonResponse(
            {"errors": {"time": "Start time must be before end time."}}, status=400
        )

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

    try:
        block = TimeBlock(
            schedule=schedule,
            title=title,
            start_time=start,
            end_time=end,
            category=data.get("category", "other"),
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

    try:
        if "title" in data:
            block.title = data["title"].strip() if isinstance(data["title"], str) else data["title"]
        if "is_completed" in data:
            block.is_completed = data["is_completed"]
        if "category" in data:
            block.category = data["category"]
        if "start_time" in data:
            block.start_time = _parse_time(data["start_time"])
        if "end_time" in data:
            block.end_time = _parse_time(data["end_time"])
        if "sort_order" in data:
            block.sort_order = data["sort_order"]
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
    except ValueError:
        return JsonResponse({"errors": {"fields": "Invalid field value."}}, status=400)
    except KeyError as e:
        return JsonResponse({"errors": {str(e).strip("'\""): "This field is required."}}, status=400)
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    return JsonResponse(_block_to_dict(block))
