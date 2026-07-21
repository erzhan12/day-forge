import datetime
import json
import logging
import time

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.http import (
    VALID_CATEGORIES,
    block_to_dict,
    is_plain_int,
    parse_time,
    parse_time_or_error,
    reject_oversized_body,
    validate_block_times,
    validate_five_minute_or_error,
    validate_sort_order,
    validate_time_range,
)
from schedules.models import Schedule, TimeBlock

logger = logging.getLogger(__name__)

MAX_REORDER_UPDATES = 100

# Private aliases so the long-standing intra-file call sites below keep
# compiling after helpers moved to ``schedules/http.py``. New code (and
# cross-app callers) should import the public names directly from
# ``schedules.http``.
_reject_oversized_body = reject_oversized_body
_is_plain_int = is_plain_int
_parse_time = parse_time
_parse_time_or_error = parse_time_or_error
_validate_five_minute_or_error = validate_five_minute_or_error
_validate_time_range = validate_time_range
_validate_block_times = validate_block_times
_validate_sort_order = validate_sort_order
_block_to_dict = block_to_dict


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
            # Parent-row lock serializes with ``_apply_draft_sync`` (which
            # also locks the Schedule row) so a concurrent draft apply on an
            # empty day can't race past the in-lock emptiness check while we
            # insert. Locking only overlapping TimeBlock rows acquires zero
            # locks on an empty schedule — see ``ai.views._apply_draft_sync``.
            Schedule.objects.select_for_update().get(pk=schedule.pk)
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

    schedule.mark_active_on_edit()
    return JsonResponse(_block_to_dict(block), status=201)


@login_required
@require_http_methods(["POST"])
def create_block_from_event(request, date):
    """Create a block from an external calendar event (feature 0026).

    A trimmed copy of ``create_block`` **minus the 5-minute granularity
    check** — external events carry arbitrary minutes (e.g. 14:07) and the
    clamp-to-day decision produces 23:59. Kept as a dedicated endpoint so
    the off-grid bypass stays off the main manual-create path; this is the
    single sanctioned off-grid caller. Every other invariant (title,
    category, ``start < end``, overlap, locking) matches ``create_block``.
    """
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

    # Explicit type checks: ``create_block`` would 500 on a non-string
    # title (``.strip()`` → AttributeError) or an unhashable category
    # (``in``-set → TypeError); don't inherit that hole here.
    for field in ("start_time", "end_time"):
        if field not in data:
            return JsonResponse(
                {"errors": {field: f"{field} is required."}}, status=400
            )
        if not isinstance(data[field], str):
            return JsonResponse(
                {"errors": {field: f"{field} must be a string."}}, status=400
            )
    if "title" in data and not isinstance(data["title"], str):
        return JsonResponse(
            {"errors": {"title": "Title must be a string."}}, status=400
        )
    if "category" in data and not isinstance(data["category"], str):
        return JsonResponse(
            {"errors": {"category": "Category must be a string."}}, status=400
        )

    schedule, _ = Schedule.objects.get_or_create(user=request.user, date=parsed_date)

    # No ``validate_five_minute_or_error`` — off-grid times are the point.
    start, err = _parse_time_or_error("start_time", data["start_time"])
    if err is not None:
        return err
    end, err = _parse_time_or_error("end_time", data["end_time"])
    if err is not None:
        return err
    # Guards the degenerate clamp where a fully-out-of-day event collapses
    # to a zero-length range: 400 instead of a zero-length block.
    err = _validate_time_range(start, end)
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

    try:
        with transaction.atomic():
            # Same locked-insert pattern as ``create_block`` — see the
            # comments there for the draft-apply serialization rationale.
            Schedule.objects.select_for_update().get(pk=schedule.pk)
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
            # ``exclude`` skips only the field-level five-minute validators;
            # range was checked above and model ``clean()`` still runs.
            block.full_clean(exclude=["start_time", "end_time"])
            block.save()
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    schedule.mark_active_on_edit()
    return JsonResponse(_block_to_dict(block), status=201)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def block_detail(request, pk):
    try:
        block = TimeBlock.objects.select_related("schedule").get(pk=pk)
    except TimeBlock.DoesNotExist:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)

    if block.schedule.user != request.user:
        # Return 404 (not 403) when the caller doesn't own the block:
        # a 403 would confirm that the requested ``pk`` exists in the DB,
        # letting an authenticated attacker enumerate block IDs outside
        # their own schedule. 403 is reserved for CSRF/middleware
        # rejections. See OWASP "Broken Authorization" guidance.
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)

    if request.method == "DELETE":
        schedule = block.schedule
        block.delete()
        schedule.mark_active_on_edit()
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
                #
                # Materialise the locked queryset so the row locks are
                # acquired now, and pull the target block out of it so we
                # don't pay for a second SELECT just to refresh the same
                # row that's already in memory under the lock.
                schedule_blocks = list(
                    TimeBlock.objects
                    .filter(schedule_id=schedule_id)
                    .select_for_update()
                )
                block = next((b for b in schedule_blocks if b.pk == pk), None)
                if block is None:
                    return JsonResponse(
                        {"errors": {"detail": "Not found."}}, status=404
                    )
            else:
                # No time change → no schedule-wide lock needed. Re-read
                # the target block so we pick up any committed changes
                # and refuse stale writes. A concurrent delete surfaces
                # cleanly as a 404.
                try:
                    block = TimeBlock.objects.select_related("schedule").get(pk=pk)
                except TimeBlock.DoesNotExist:
                    return JsonResponse(
                        {"errors": {"detail": "Not found."}}, status=404
                    )

            stored_start, stored_end = block.start_time, block.end_time

            for field, value in pending.items():
                setattr(block, field, value)

            if time_change:
                # Granularity only on times the client actually *changed*
                # (feature 0026): a PATCH that alters only ``end_time`` on an
                # off-grid from-event block must not re-fail the inherited
                # off-grid ``start_time``, and re-submitting a stored off-grid
                # value unchanged must not 400 either. Identical rule to
                # ``reorder_blocks`` — the two paths validate the same way.
                changed = [
                    t
                    for t, stored, key in (
                        (block.start_time, stored_start, "start_time"),
                        (block.end_time, stored_end, "end_time"),
                    )
                    if key in pending and t != stored
                ]
                if changed:
                    err = _validate_five_minute_or_error(*changed)
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

            # ``exclude`` keeps a completion toggle / title edit on an
            # off-grid from-event block (feature 0026) from re-failing the
            # field-level five-minute validators on *unchanged* times.
            # Manual time edits enforced granularity + range explicitly
            # above; model ``clean()`` (start >= end) still runs.
            block.full_clean(exclude=["start_time", "end_time"])
            block.save()
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    block.schedule.mark_active_on_edit()
    return JsonResponse(_block_to_dict(block))


@login_required
@require_http_methods(["POST"])
def reorder_blocks(request):
    """Atomically apply a batch of block time/order updates.

    Deployment note: per-request validation caps the payload at 100 blocks
    (see ``MAX_REORDER_UPDATES`` below) and the raw body at
    ``MAX_REQUEST_BODY_BYTES``, but that does not rate-limit the *frequency*
    of requests. Production deployments should layer on a request-rate
    limit at the reverse proxy to prevent DoS via rapid repeated reorders
    against the locked overlap scan.

    Example nginx config (place in ``http`` / ``server`` blocks)::

        # Define a 10 MB shared zone, 10 requests/minute per client IP.
        # 10 r/m is generous — a real drag-and-drop user triggers at
        # most a handful of reorders per minute.
        limit_req_zone $binary_remote_addr zone=reorder:10m rate=10r/m;

        location = /api/blocks/reorder/ {
            limit_req zone=reorder burst=5 nodelay;
            proxy_pass http://django_upstream;
        }

    API gateways (Kong, APISIX, Cloudflare, AWS API Gateway) expose
    equivalent rate-limit primitives — pick whichever lives closest to
    your edge.
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

    # Validate each update entry's contents (no DB access required).
    # Granularity is deferred to the in-lock loop below: a drag payload
    # renumbers *every* block's sort_order and re-submits unchanged
    # (possibly off-grid, feature 0026) times, which must not 400. Format
    # and range always run here; the batch overlap check runs in-lock.
    for uid, entry in update_map.items():
        for field in ("start_time", "end_time", "sort_order"):
            if field not in entry:
                return JsonResponse(
                    {"errors": {field: f"{field} is required for block {uid}."}},
                    status=400,
                )
        _, _, err = _validate_block_times(
            entry["start_time"], entry["end_time"], block_id=uid,
            enforce_granularity=False,
        )
        if err is not None:
            return err
        err = _validate_sort_order(entry["sort_order"], block_id=uid)
        if err is not None:
            return err

    t0 = time.monotonic()
    schedule = None
    try:
        with transaction.atomic():
            # Single locked SELECT that both fetches and row-locks every
            # block belonging to any schedule that contains at least one
            # requested ID. Reading the two lines carefully:
            #
            #   * The INNER queryset
            #     ``TimeBlock.objects.filter(id__in=ids).values("schedule")``
            #     is intentionally left lazy. Django inlines it as a
            #     subquery and the whole thing compiles to one statement:
            #       SELECT ... WHERE schedule_id IN
            #         (SELECT schedule_id FROM ... WHERE id IN (...))
            #       FOR UPDATE;
            #     Do NOT wrap the inner queryset in ``list()`` / ``len()``
            #     / a loop — materialising it would split this into two
            #     separate statements, the first one unlocked, opening a
            #     TOCTOU window where a concurrent writer could move a
            #     block between schedules between the two reads.
            #
            #   * The OUTER ``list(...)`` here is the opposite — it
            #     *must* materialise the final queryset under the
            #     ``select_for_update`` lock, inside the ``atomic()``
            #     block, so the row locks are acquired immediately and
            #     held for the whole transaction. Without ``list(...)``
            #     the queryset would stay lazy and the lock would only
            #     fire when the rows are actually iterated — potentially
            #     outside the ``atomic()`` block. Evaluate-now is the
            #     whole point.
            #
            # SQLite silently ignores ``select_for_update`` (see the
            # ``schedules.W001`` system check); PostgreSQL honours it.
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
                # A requested ID that isn't in ``schedule_blocks`` does not
                # exist in the DB: the outer fetch pulls every row for any
                # schedule that contains a requested ID, so if the row were
                # live it would have been included. Return 404 without any
                # further probing — an extra existence query here would
                # only leak information about IDs in other users' schedules.
                return JsonResponse(
                    {"errors": {"detail": "One or more blocks not found."}},
                    status=404,
                )

            # All requested IDs are present and live in a single schedule.
            schedule = blocks_by_id[ids[0]].schedule
            if schedule.user != request.user:
                # 404 (not 403) on cross-user access — see the matching
                # comment in ``block_detail`` for the rationale.
                return JsonResponse(
                    {"errors": {"detail": "One or more blocks not found."}},
                    status=404,
                )

            # Build the candidate state from the in-memory blocks (no extra
            # query) by mutating the updated blocks in place and including
            # every schedule block in the overlap candidates.
            blocks_to_save = []
            for b in schedule_blocks:
                if b.id in update_map:
                    entry = update_map[b.id]
                    new_start = _parse_time(entry["start_time"])
                    new_end = _parse_time(entry["end_time"])
                    # Enforce granularity only on times that actually
                    # changed: unchanged off-grid times (from-event
                    # blocks, feature 0026) were already persisted as
                    # valid; a *new* off-grid time still 400s.
                    changed = [
                        t for t, stored in (
                            (new_start, b.start_time),
                            (new_end, b.end_time),
                        )
                        if t != stored
                    ]
                    if changed:
                        err = _validate_five_minute_or_error(*changed)
                        if err is not None:
                            return err
                    b.start_time = new_start
                    b.end_time = new_end
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
                # Same footgun as ``block_detail``: the field validators
                # would re-fail unchanged off-grid times even after the
                # selective granularity check above. Range and overlap
                # were checked explicitly; model ``clean()`` still runs.
                b.full_clean(exclude=["start_time", "end_time"])
                b.save()
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    # Return full block list for the schedule
    result_blocks = TimeBlock.objects.filter(schedule=schedule).order_by(
        "start_time", "sort_order"
    )
    logger.info(
        "reorder_blocks: %d updates, %.3fs",
        len(updates), time.monotonic() - t0,
    )
    if schedule is not None:
        schedule.mark_active_on_edit()
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
        # Restore re-persists previously-valid states, which may include
        # off-grid from-event blocks (feature 0026) — skip only the
        # granularity check; format, range, and the snapshot-overlap
        # check below all stay.
        start, end, err = _validate_block_times(
            entry["start_time"], entry["end_time"], block_id=i,
            enforce_granularity=False,
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

    # Apply atomically: delete all existing, then create the snapshot
    # in a single ``bulk_create`` call. ``bulk_create`` skips
    # ``Model.save()`` and ``Model.full_clean()``, so we explicitly
    # ``full_clean()`` every instance in a pre-pass first — if any
    # block is invalid the whole request 400s before we touch the DB,
    # so atomicity holds trivially.
    t0 = time.monotonic()
    try:
        instances = [
            TimeBlock(
                schedule=schedule,
                title=v["title"],
                start_time=v["start_time"],
                end_time=v["end_time"],
                category=v["category"],
                is_completed=v["is_completed"],
                sort_order=v["sort_order"],
            )
            for v in validated
        ]
        for block in instances:
            # Skip the field-level five-minute validators (off-grid
            # from-event blocks restore verbatim); everything else —
            # title/category field validation, model ``clean()`` — runs.
            block.full_clean(exclude=["start_time", "end_time"])

        with transaction.atomic():
            # Same parent-row lock as ``create_block`` — draft apply holds
            # this lock while re-checking emptiness, so restore must queue
            # behind it (and vice versa) on PostgreSQL.
            Schedule.objects.select_for_update().get(pk=schedule.pk)
            TimeBlock.objects.filter(schedule=schedule).delete()
            if instances:
                TimeBlock.objects.bulk_create(instances)
    except ValidationError as e:
        return JsonResponse({"errors": e.message_dict}, status=400)

    result_blocks = TimeBlock.objects.filter(schedule=schedule).order_by(
        "start_time", "sort_order"
    )
    logger.info(
        "restore_blocks: %d blocks, %.3fs",
        len(validated), time.monotonic() - t0,
    )
    return JsonResponse(
        {"blocks": [_block_to_dict(b) for b in result_blocks]},
    )
