import datetime
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.models import Schedule, TimeBlock
from schedules.validators import validate_five_minute_granularity

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
                # Lock candidate-overlap rows to serialize concurrent edits
                # under PostgreSQL. SQLite ignores select_for_update silently.
                overlap = TimeBlock.objects.filter(
                    schedule=block.schedule,
                    start_time__lt=block.end_time,
                    end_time__gt=block.start_time,
                ).exclude(pk=block.pk).select_for_update().exists()
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


@login_required
@require_http_methods(["POST"])
def reorder_blocks(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"errors": {"body": "Invalid JSON."}}, status=400)

    if not isinstance(data, dict):
        return JsonResponse(
            {"errors": {"body": "Request body must be a JSON object."}},
            status=400,
        )

    updates = data.get("updates")
    if not isinstance(updates, list) or len(updates) == 0:
        return JsonResponse(
            {"errors": {"updates": "A non-empty list of updates is required."}},
            status=400,
        )

    # Validate each entry is a dict with an integer id
    for i, u in enumerate(updates):
        if not isinstance(u, dict):
            return JsonResponse(
                {"errors": {"updates": f"Entry {i} must be an object."}},
                status=400,
            )
        uid = u.get("id")
        if uid is None or isinstance(uid, bool) or not isinstance(uid, int):
            return JsonResponse(
                {"errors": {"updates": f"Entry {i} must have an integer 'id'."}},
                status=400,
            )

    # Check for duplicate IDs
    ids = [u["id"] for u in updates]
    if len(ids) != len(set(ids)):
        return JsonResponse(
            {"errors": {"updates": "Duplicate block IDs in request."}}, status=400
        )

    update_map = {u["id"]: u for u in updates}

    # Validate each update entry's contents (no DB access required)
    for uid, entry in update_map.items():
        for field in ("start_time", "end_time", "sort_order"):
            if field not in entry:
                return JsonResponse(
                    {"errors": {field: f"{field} is required for block {uid}."}},
                    status=400,
                )
        try:
            start = _parse_time(entry["start_time"])
        except (ValueError, TypeError):
            return JsonResponse(
                {"errors": {"start_time": f"Invalid time format for block {uid}. Use HH:MM."}},
                status=400,
            )
        try:
            end = _parse_time(entry["end_time"])
        except (ValueError, TypeError):
            return JsonResponse(
                {"errors": {"end_time": f"Invalid time format for block {uid}. Use HH:MM."}},
                status=400,
            )
        try:
            validate_five_minute_granularity(start)
            validate_five_minute_granularity(end)
        except ValidationError as e:
            return JsonResponse({"errors": {"time": str(e.message)}}, status=400)
        if start >= end:
            return JsonResponse(
                {"errors": {"time": f"Start time must be before end time for block {uid}."}},
                status=400,
            )
        sort_order = entry["sort_order"]
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            return JsonResponse(
                {"errors": {"sort_order": "sort_order must be an integer."}}, status=400
            )
        if not (0 <= sort_order <= 10_000):
            return JsonResponse(
                {"errors": {"sort_order": "sort_order must be between 0 and 10000."}},
                status=400,
            )

    schedule = None
    try:
        with transaction.atomic():
            # Single locked query: fetch every block for any schedule that
            # contains at least one of the requested IDs. This both eliminates
            # the previous two-query pattern (one for the requested blocks, one
            # for the full schedule needed to check overlaps) and locks the
            # affected rows for the duration of the transaction. SQLite
            # silently ignores select_for_update; PostgreSQL respects it.
            schedule_blocks = list(
                TimeBlock.objects.select_related("schedule__user")
                .filter(
                    schedule__in=TimeBlock.objects.filter(id__in=ids).values(
                        "schedule"
                    )
                )
                .select_for_update()
            )

            blocks_by_id = {b.id: b for b in schedule_blocks}
            present_ids = set(blocks_by_id.keys())
            requested_ids = set(ids)
            missing = requested_ids - present_ids

            # Cross-schedule check first: if the requested blocks straddle
            # multiple schedules, that is a 400 regardless of ownership.
            requested_schedule_ids = {
                blocks_by_id[i].schedule_id for i in requested_ids if i in blocks_by_id
            }
            if len(requested_schedule_ids) > 1:
                return JsonResponse(
                    {
                        "errors": {
                            "updates": "All blocks must belong to the same schedule."
                        }
                    },
                    status=400,
                )

            if missing:
                # Differentiate "exists but caller cannot see it" (403) from
                # "does not exist anywhere" (404), matching block_detail's
                # auth pattern. Both are independent of the user's session.
                exists_elsewhere = TimeBlock.objects.filter(
                    id__in=missing
                ).exists()
                if exists_elsewhere:
                    return JsonResponse(
                        {"errors": {"detail": "Forbidden."}}, status=403
                    )
                return JsonResponse(
                    {"errors": {"detail": "One or more blocks not found."}},
                    status=404,
                )

            # All requested IDs are present and live in a single schedule.
            schedule = blocks_by_id[ids[0]].schedule
            if schedule.user != request.user:
                return JsonResponse(
                    {"errors": {"detail": "Forbidden."}}, status=403
                )

            # Build the candidate state from the in-memory blocks (no extra
            # query) by mutating the updated blocks in place and including
            # every schedule block in the overlap candidates.
            blocks_to_save = []
            for b in schedule_blocks:
                if b.id in update_map:
                    entry = update_map[b.id]
                    b.start_time = _parse_time(entry["start_time"])
                    b.end_time = _parse_time(entry["end_time"])
                    b.sort_order = entry["sort_order"]
                    blocks_to_save.append(b)

            candidates = sorted(
                ((b.start_time, b.end_time, b.sort_order) for b in schedule_blocks),
                key=lambda c: (c[0], c[2]),
            )
            for i in range(len(candidates) - 1):
                if candidates[i][1] > candidates[i + 1][0]:
                    return JsonResponse(
                        {
                            "errors": {
                                "time": "Reorder would cause overlapping blocks."
                            }
                        },
                        status=400,
                    )

            for b in blocks_to_save:
                b.full_clean()
                b.save()
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    # Return full block list for the schedule
    result_blocks = TimeBlock.objects.filter(schedule=schedule).order_by(
        "start_time", "sort_order"
    )
    return JsonResponse(
        {"blocks": [_block_to_dict(b) for b in result_blocks]},
    )


@login_required
@require_http_methods(["POST"])
def restore_blocks(request, date):
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return JsonResponse({"errors": {"date": "Invalid date format."}}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"errors": {"body": "Invalid JSON."}}, status=400)

    if not isinstance(data, dict):
        return JsonResponse(
            {"errors": {"body": "Request body must be a JSON object."}},
            status=400,
        )

    blocks_data = data.get("blocks")
    if not isinstance(blocks_data, list):
        return JsonResponse(
            {"errors": {"blocks": "A list of blocks is required."}}, status=400
        )

    schedule, _ = Schedule.objects.get_or_create(user=request.user, date=parsed_date)

    # Validate each block entry
    validated = []
    for i, entry in enumerate(blocks_data):
        if not isinstance(entry, dict):
            return JsonResponse(
                {"errors": {"blocks": f"Entry {i} must be an object."}},
                status=400,
            )
        # Title
        title = entry.get("title", "")
        if not isinstance(title, str):
            return JsonResponse(
                {"errors": {"title": f"Title must be a string (block {i})."}}, status=400
            )
        title = title.strip()
        if not title:
            return JsonResponse(
                {"errors": {"title": f"Title is required (block {i})."}}, status=400
            )
        if len(title) > 255:
            return JsonResponse(
                {"errors": {"title": f"Title too long (block {i})."}}, status=400
            )

        # Times
        for field in ("start_time", "end_time"):
            if field not in entry:
                return JsonResponse(
                    {"errors": {field: f"{field} is required (block {i})."}}, status=400
                )
        try:
            start = _parse_time(entry["start_time"])
        except (ValueError, TypeError):
            return JsonResponse(
                {"errors": {"start_time": f"Invalid time format (block {i})."}},
                status=400,
            )
        try:
            end = _parse_time(entry["end_time"])
        except (ValueError, TypeError):
            return JsonResponse(
                {"errors": {"end_time": f"Invalid time format (block {i})."}},
                status=400,
            )
        try:
            validate_five_minute_granularity(start)
            validate_five_minute_granularity(end)
        except ValidationError as e:
            return JsonResponse({"errors": {"time": str(e.message)}}, status=400)
        if start >= end:
            return JsonResponse(
                {"errors": {"time": f"Start time must be before end time (block {i})."}},
                status=400,
            )

        # Category
        category = entry.get("category", "other")
        if category not in VALID_CATEGORIES:
            choices = ", ".join(sorted(VALID_CATEGORIES))
            return JsonResponse(
                {"errors": {"category": f"Invalid category (block {i}). Choose from: {choices}."}},
                status=400,
            )

        # is_completed
        is_completed = entry.get("is_completed", False)
        if not isinstance(is_completed, bool):
            return JsonResponse(
                {"errors": {"is_completed": f"is_completed must be a boolean (block {i})."}},
                status=400,
            )

        # sort_order
        sort_order = entry.get("sort_order", 0)
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            return JsonResponse(
                {"errors": {"sort_order": f"sort_order must be an integer (block {i})."}},
                status=400,
            )
        if not (0 <= sort_order <= 10_000):
            return JsonResponse(
                {"errors": {"sort_order": f"sort_order must be between 0 and 10000 (block {i})."}},
                status=400,
            )

        validated.append({
            "title": title,
            "start_time": start,
            "end_time": end,
            "category": category,
            "is_completed": is_completed,
            "sort_order": sort_order,
        })

    # Check for overlaps in the candidate set
    validated.sort(key=lambda v: (v["start_time"], v["sort_order"]))
    for i in range(len(validated) - 1):
        if validated[i]["end_time"] > validated[i + 1]["start_time"]:
            return JsonResponse(
                {"errors": {"time": "Restored blocks would overlap."}}, status=400
            )

    # Apply atomically: delete all existing, create from snapshot
    try:
        with transaction.atomic():
            TimeBlock.objects.filter(schedule=schedule).delete()
            for v in validated:
                block = TimeBlock(
                    schedule=schedule,
                    title=v["title"],
                    start_time=v["start_time"],
                    end_time=v["end_time"],
                    category=v["category"],
                    is_completed=v["is_completed"],
                    sort_order=v["sort_order"],
                )
                block.full_clean()
                block.save()
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    result_blocks = TimeBlock.objects.filter(schedule=schedule).order_by(
        "start_time", "sort_order"
    )
    return JsonResponse(
        {"blocks": [_block_to_dict(b) for b in result_blocks]},
    )
