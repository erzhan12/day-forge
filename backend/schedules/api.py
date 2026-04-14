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
MAX_SORT_ORDER = 10_000
MAX_REORDER_UPDATES = 100
# Tight body-size cap for the batch endpoints. Django already enforces
# ``DATA_UPLOAD_MAX_MEMORY_SIZE`` (2.5 MB default), but at ~100 bytes/block
# a legitimate payload is well under 20 KB — 100 KB is 5× headroom and
# avoids parsing several megabytes of JSON only to reject it via the
# per-entry count/field checks below. Returns HTTP 413 when exceeded.
MAX_REQUEST_BODY_BYTES = 100_000


def _reject_oversized_body(request):
    """Return a 413 ``JsonResponse`` if ``request.body`` exceeds the cap,
    otherwise ``None``. Call before ``json.loads`` in batch endpoints."""
    if len(request.body) > MAX_REQUEST_BODY_BYTES:
        return JsonResponse(
            {"errors": {"body": "Request body too large."}},
            status=413,
        )
    return None


def _is_plain_int(value) -> bool:
    """True if ``value`` is an ``int`` that isn't a ``bool``.

    Python's ``bool`` is a subclass of ``int``, so a bare
    ``isinstance(value, int)`` check accepts ``True``/``False`` as valid
    integers. Every call site that needs a "real" integer must guard
    against that, and centralising the check here keeps the rationale
    in one place.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_time(value):
    """Parse 'HH:MM' string to datetime.time."""
    return datetime.datetime.strptime(value, "%H:%M").time()


def _parse_time_or_error(field_name, value, block_id=None):
    """Parse an HH:MM string. Return ``(time, None)`` on success or
    ``(None, JsonResponse)`` with a 400 error on failure.

    ``block_id`` is appended to the error message when supplied so callers
    handling lists of entries can disambiguate which one was malformed.
    """
    suffix = f" for block {block_id}" if block_id is not None else ""
    try:
        return _parse_time(value), None
    except (ValueError, TypeError):
        return None, JsonResponse(
            {"errors": {field_name: f"Invalid time format{suffix}. Use HH:MM."}},
            status=400,
        )


def _validate_five_minute_or_error(*times):
    """Run ``validate_five_minute_granularity`` on every value. Return ``None``
    on success or a 400 ``JsonResponse`` on the first failure."""
    try:
        for t in times:
            validate_five_minute_granularity(t)
    except ValidationError as e:
        return JsonResponse({"errors": {"time": str(e.message)}}, status=400)
    return None


def _validate_time_range(start, end, block_id=None):
    """Verify ``start < end``. Return ``None`` on success or a 400
    ``JsonResponse`` otherwise."""
    if start >= end:
        suffix = f" for block {block_id}" if block_id is not None else ""
        return JsonResponse(
            {"errors": {"time": f"Start time must be before end time{suffix}."}},
            status=400,
        )
    return None


def _validate_block_times(start_str, end_str, block_id=None):
    """Parse and validate a pair of HH:MM strings: format, 5-minute
    granularity, and ``start < end``.

    Returns ``(start, end, None)`` on success or ``(None, None, JsonResponse)``
    on the first failure.
    """
    start, err = _parse_time_or_error("start_time", start_str, block_id=block_id)
    if err is not None:
        return None, None, err
    end, err = _parse_time_or_error("end_time", end_str, block_id=block_id)
    if err is not None:
        return None, None, err
    err = _validate_five_minute_or_error(start, end)
    if err is not None:
        return None, None, err
    err = _validate_time_range(start, end, block_id=block_id)
    if err is not None:
        return None, None, err
    return start, end, None


def _validate_sort_order(value, block_id=None):
    """Verify ``value`` is an integer in ``[0, MAX_SORT_ORDER]``. Return
    ``None`` on success or a 400 ``JsonResponse`` otherwise.
    """
    suffix = f" for block {block_id}" if block_id is not None else ""
    if not _is_plain_int(value):
        return JsonResponse(
            {"errors": {"sort_order": f"sort_order must be an integer{suffix}."}},
            status=400,
        )
    if not (0 <= value <= MAX_SORT_ORDER):
        return JsonResponse(
            {
                "errors": {
                    "sort_order": (
                        f"sort_order must be between 0 and {MAX_SORT_ORDER}"
                        f"{suffix}."
                    )
                }
            },
            status=400,
        )
    return None


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

    start, end, err = _validate_block_times(data["start_time"], data["end_time"])
    if err is not None:
        return err

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

    # Lock the candidate-overlap rows to serialize concurrent inserts under
    # PostgreSQL. SQLite ignores select_for_update silently but still
    # serializes via its DB-level write lock.
    try:
        with transaction.atomic():
            overlap = TimeBlock.objects.filter(
                schedule=schedule,
                start_time__lt=end,
                end_time__gt=start,
            ).select_for_update().exists()
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

    # Stage all incoming changes in `pending` before touching the DB. Any
    # parse / type / range error returns 400 *before* we enter the atomic
    # block, so we don't hold a schedule-wide lock across validation.
    pending: dict = {}

    if "start_time" in data:
        parsed, err = _parse_time_or_error("start_time", data["start_time"])
        if err is not None:
            return err
        pending["start_time"] = parsed
    if "end_time" in data:
        parsed, err = _parse_time_or_error("end_time", data["end_time"])
        if err is not None:
            return err
        pending["end_time"] = parsed
    if "title" in data:
        if not isinstance(data["title"], str):
            return JsonResponse(
                {"errors": {"title": "Title must be a string."}}, status=400
            )
        title = data["title"].strip()
        if not title:
            return JsonResponse(
                {"errors": {"title": "Title cannot be empty."}}, status=400
            )
        if len(title) > 255:
            return JsonResponse(
                {"errors": {"title": "Title too long (max 255 characters)."}},
                status=400,
            )
        pending["title"] = title
    if "is_completed" in data:
        if not isinstance(data["is_completed"], bool):
            return JsonResponse(
                {"errors": {"is_completed": "is_completed must be a boolean."}},
                status=400,
            )
        pending["is_completed"] = data["is_completed"]
    if "category" in data:
        if data["category"] not in VALID_CATEGORIES:
            choices = ", ".join(sorted(VALID_CATEGORIES))
            return JsonResponse(
                {"errors": {"category": f"Invalid category. Choose from: {choices}."}},
                status=400,
            )
        pending["category"] = data["category"]
    if "sort_order" in data:
        err = _validate_sort_order(data["sort_order"])
        if err is not None:
            return err
        pending["sort_order"] = data["sort_order"]

    time_change = "start_time" in pending or "end_time" in pending
    schedule_id = block.schedule_id

    try:
        with transaction.atomic():
            if time_change:
                # Close the PATCH-vs-PATCH TOCTOU race: two concurrent
                # requests editing *different* blocks in the same schedule
                # can each pass their own overlap check (neither transaction
                # sees the other's pending time change) and end up
                # overlapping. Holding a schedule-wide row lock before the
                # overlap read serializes all time-changing edits through
                # one queue, which closes the window. `select_for_update`
                # is a no-op on SQLite — see schedules.W001.
                list(
                    TimeBlock.objects
                    .filter(schedule_id=schedule_id)
                    .select_for_update()
                )

            # Re-read the target block under the lock so we pick up any
            # committed changes and refuse stale writes. A concurrent
            # delete still surfaces cleanly as a 404.
            try:
                block = TimeBlock.objects.select_related("schedule").get(pk=pk)
            except TimeBlock.DoesNotExist:
                return JsonResponse(
                    {"errors": {"detail": "Not found."}}, status=404
                )

            for field, value in pending.items():
                setattr(block, field, value)

            if time_change:
                err = _validate_five_minute_or_error(
                    block.start_time, block.end_time
                )
                if err is not None:
                    return err
                err = _validate_time_range(block.start_time, block.end_time)
                if err is not None:
                    return err
                overlap = TimeBlock.objects.filter(
                    schedule_id=schedule_id,
                    start_time__lt=block.end_time,
                    end_time__gt=block.start_time,
                ).exclude(pk=block.pk).exists()
                if overlap:
                    return JsonResponse(
                        {
                            "errors": {
                                "time": "This block overlaps with an existing block."
                            }
                        },
                        status=400,
                    )

            block.full_clean()
            block.save()
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    return JsonResponse(_block_to_dict(block))


@login_required
@require_http_methods(["POST"])
def reorder_blocks(request):
    """Atomically apply a batch of block time/order updates.

    Deployment note: per-request validation caps the payload at 100 blocks
    (see ``MAX_REORDER_UPDATES`` below) and the raw body at
    ``MAX_REQUEST_BODY_BYTES``, but that does not rate-limit the *frequency*
    of requests. Production deployments should layer on a request-rate
    limit at the reverse proxy (e.g. ``limit_req`` in nginx or an API
    gateway equivalent) to prevent DoS via rapid repeated reorders against
    the locked overlap scan.
    """
    oversized = _reject_oversized_body(request)
    if oversized is not None:
        return oversized

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

    # Defensive cap: a single drag in the UI only ever touches a handful of
    # blocks. Reject pathological payloads up-front so a malicious client
    # cannot force an expensive validation + locked overlap scan.
    if len(updates) > MAX_REORDER_UPDATES:
        return JsonResponse(
            {
                "errors": {
                    "updates": (
                        f"Cannot update more than {MAX_REORDER_UPDATES} "
                        f"blocks at once."
                    )
                }
            },
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
        if uid is None or not _is_plain_int(uid):
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
        _, _, err = _validate_block_times(
            entry["start_time"], entry["end_time"], block_id=uid
        )
        if err is not None:
            return err
        err = _validate_sort_order(entry["sort_order"], block_id=uid)
        if err is not None:
            return err

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

    oversized = _reject_oversized_body(request)
    if oversized is not None:
        return oversized

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
        start, end, err = _validate_block_times(
            entry["start_time"], entry["end_time"], block_id=i
        )
        if err is not None:
            return err

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
        err = _validate_sort_order(sort_order, block_id=i)
        if err is not None:
            return err

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
