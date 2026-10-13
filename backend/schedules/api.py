"""HTTP adapters for schedule commands.

Transport parsing and category ownership live here. The planner validates the
complete candidate schedule, and the R04 executor owns the atomic write.
"""

import datetime
import logging
import time
from functools import wraps

from common.http import parse_json_object
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.categories import default_category, ordered_categories, sink_category, validate_slug
from schedules.commands import (
    CreateCommand,
    DeleteCommand,
    ReorderCommand,
    RestoreCommand,
    UpdateCommand,
)
from schedules.http import (
    is_plain_int,
    parse_time_or_error,
    validate_block_times,
    validate_sort_order,
)
from schedules.models import TimeBlock
from schedules.mutations import (
    MutationRejected,
    ScheduleChanged,
    execute_schedule_mutation,
    parse_expected_revision,
    schedule_changed_response,
)
from schedules.persistence import persist_command_diff
from schedules.planning import (
    IMPORT,
    MANUAL,
    UNDO,
    CommandError,
    plan_commands,
    snapshot_from_blocks,
)
from schedules.provenance import origin_from_restore_proof
from schedules.serialization import serialize_block
from schedules.window import get_schedule_window

logger = logging.getLogger(__name__)
MAX_REORDER_UPDATES = 100


def _mutation_errors(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except ScheduleChanged as error:
            return schedule_changed_response(error)
        except MutationRejected as error:
            return error.response

    return wrapped


def _outside_window_response(window):
    return JsonResponse(
        {
            "skipped": True,
            "code": "outside_window",
            "detail": "Block is outside your day window.",
            "window": {"start": window.start_str, "end": window.end_str},
            "errors": {"time": "Block is outside your day window."},
        },
        status=422,
    )


def _plan_error_response(error, *, overlap_message, window=None, missing_message="Not found."):
    if error.code == "out_of_window":
        return _outside_window_response(window)
    if error.code == "unknown_block":
        return JsonResponse({"errors": {"detail": missing_message}}, status=404)
    message = overlap_message if error.code == "overlap" else error.message
    return JsonResponse({"errors": {error.field: message}}, status=400)


def _date_or_error(value):
    try:
        return datetime.date.fromisoformat(value), None
    except ValueError:
        return None, JsonResponse({"errors": {"date": "Invalid date format."}}, status=400)


def _parse_required_times(data, *, block_id=None):
    for field in ("start_time", "end_time"):
        if field not in data:
            suffix = f" (block {block_id})" if block_id is not None else ""
            message = (
                f"{field} is required{suffix}." if block_id is not None else f"{field} is required."
            )
            return None, None, JsonResponse({"errors": {field: message}}, status=400)
        if block_id is None and not isinstance(data[field], str):
            return (
                None,
                None,
                JsonResponse({"errors": {field: f"{field} must be a string."}}, status=400),
            )
    start, error = parse_time_or_error("start_time", data["start_time"], block_id=block_id)
    if error is not None:
        return None, None, error
    end, error = parse_time_or_error("end_time", data["end_time"], block_id=block_id)
    return start, end, error


def _create_block(request, date, *, policy):
    parsed_date, error = _date_or_error(date)
    if error is not None:
        return error
    data, error = parse_json_object(request)
    if error is not None:
        return error
    for field in ("start_time", "end_time"):
        if field not in data:
            return JsonResponse({"errors": {field: f"{field} is required."}}, status=400)
        if not isinstance(data[field], str):
            return JsonResponse({"errors": {field: f"{field} must be a string."}}, status=400)
    if "title" in data and not isinstance(data["title"], str):
        return JsonResponse({"errors": {"title": "Title must be a string."}}, status=400)
    if "category" in data and not isinstance(data["category"], str):
        return JsonResponse({"errors": {"category": "Category must be a string."}}, status=400)
    start, end, error = _parse_required_times(data)
    if error is not None:
        return error
    _, _, error = validate_block_times(
        data["start_time"], data["end_time"], enforce_granularity=policy == MANUAL
    )
    if error is not None:
        return error
    title = data.get("title", "").strip()
    if not title:
        return JsonResponse({"errors": {"title": "Title is required."}}, status=400)
    if len(title) > 255:
        return JsonResponse(
            {"errors": {"title": "Title too long (max 255 characters)."}}, status=400
        )
    categories = ordered_categories(request.user)
    default = default_category(categories) if policy == MANUAL else sink_category(categories)
    category = data.get("category", default.slug)
    try:
        category = validate_slug(category, categories)
    except ValueError as exc:
        return JsonResponse({"errors": {"category": str(exc)}}, status=400)
    expected_revision = parse_expected_revision(data)

    def apply(ctx):
        try:
            fresh_category = validate_slug(category, ordered_categories(request.user))
        except ValueError as exc:
            return JsonResponse({"errors": {"category": str(exc)}}, status=400)
        window = get_schedule_window(request.user)
        origin = TimeBlock.Origin.CALENDAR if policy == IMPORT else TimeBlock.Origin.MANUAL
        command = CreateCommand(title, start, end, fresh_category, sort_order=0, origin=origin)
        try:
            plan = plan_commands(
                snapshot_from_blocks(ctx.schedule, ctx.blocks),
                (command,),
                policy=policy,
                window=window,
            )
        except CommandError as exc:
            return _plan_error_response(
                exc, overlap_message="This block overlaps with an existing block.", window=window
            )
        created = persist_command_diff(ctx.schedule, ctx.blocks, plan.diff)
        ctx.schedule.mark_active_on_edit()
        return serialize_block(created[0])

    result = execute_schedule_mutation(
        request.user.pk, None, expected_revision, apply, date=parsed_date
    )
    return JsonResponse({**result.value, **result.snapshot}, status=201)


@login_required
@require_http_methods(["POST"])
@_mutation_errors
def create_block(request, date):
    return _create_block(request, date, policy=MANUAL)


@login_required
@require_http_methods(["POST"])
@_mutation_errors
def create_block_from_event(request, date):
    return _create_block(request, date, policy=IMPORT)


@login_required
@require_http_methods(["PATCH", "DELETE"])
@_mutation_errors
def block_detail(request, pk):
    try:
        block = TimeBlock.objects.select_related("schedule").get(pk=pk)
    except TimeBlock.DoesNotExist:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    if block.schedule.user_id != request.user.pk:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    data, error = parse_json_object(request, allow_empty=request.method == "DELETE")
    if error is not None:
        return error
    schedule_id = block.schedule_id

    if request.method == "DELETE":
        expected_revision = parse_expected_revision(data)

        def apply_delete(ctx):
            try:
                plan = plan_commands(
                    snapshot_from_blocks(ctx.schedule, ctx.blocks),
                    (DeleteCommand(pk),),
                    policy=MANUAL,
                )
            except CommandError as exc:
                return _plan_error_response(
                    exc, overlap_message="This block overlaps with an existing block."
                )
            persist_command_diff(ctx.schedule, ctx.blocks, plan.diff)
            ctx.schedule.mark_active_on_edit()
            return {"ok": True}

        result = execute_schedule_mutation(
            request.user.pk, schedule_id, expected_revision, apply_delete
        )
        return JsonResponse({**result.value, **result.snapshot})

    pending = {}
    for field in ("start_time", "end_time"):
        if field in data:
            parsed, error = parse_time_or_error(field, data[field])
            if error is not None:
                return error
            pending[field] = parsed
    if "title" in data:
        if not isinstance(data["title"], str):
            return JsonResponse({"errors": {"title": "Title must be a string."}}, status=400)
        title = data["title"].strip()
        if not title:
            return JsonResponse({"errors": {"title": "Title cannot be empty."}}, status=400)
        if len(title) > 255:
            return JsonResponse(
                {"errors": {"title": "Title too long (max 255 characters)."}}, status=400
            )
        pending["title"] = title
    if "is_completed" in data:
        if not isinstance(data["is_completed"], bool):
            return JsonResponse(
                {"errors": {"is_completed": "is_completed must be a boolean."}}, status=400
            )
        pending["is_completed"] = data["is_completed"]
    if "category" in data:
        if not isinstance(data["category"], str):
            return JsonResponse({"errors": {"category": "Category must be a string."}}, status=400)
        try:
            validate_slug(data["category"], ordered_categories(request.user))
        except ValueError as exc:
            return JsonResponse({"errors": {"category": str(exc)}}, status=400)
        pending["category"] = data["category"]
    if "sort_order" in data:
        error = validate_sort_order(data["sort_order"])
        if error is not None:
            return error
        pending["sort_order"] = data["sort_order"]

    expected_revision = parse_expected_revision(data)

    def apply(ctx):
        target = next((item for item in ctx.blocks if item.pk == pk), None)
        if target is None:
            return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
        if "category" in pending:
            try:
                validate_slug(pending["category"], ordered_categories(request.user))
            except ValueError as exc:
                return JsonResponse({"errors": {"category": str(exc)}}, status=400)
        window = get_schedule_window(request.user)
        try:
            plan = plan_commands(
                snapshot_from_blocks(ctx.schedule, ctx.blocks),
                (UpdateCommand(pk, **pending),),
                policy=MANUAL,
                window=window,
            )
        except CommandError as exc:
            return _plan_error_response(
                exc, overlap_message="This block overlaps with an existing block.", window=window
            )
        persist_command_diff(ctx.schedule, ctx.blocks, plan.diff)
        if plan.diff.updates:
            ctx.schedule.mark_active_on_edit()
        return serialize_block(target)

    result = execute_schedule_mutation(request.user.pk, schedule_id, expected_revision, apply)
    return JsonResponse({**result.value, **result.snapshot})


@login_required
@require_http_methods(["POST"])
@_mutation_errors
def reorder_blocks(request):
    """Apply a batch against the final candidate schedule under one lock."""
    data, error = parse_json_object(request)
    if error is not None:
        return error
    updates = data.get("updates")
    if not isinstance(updates, list) or not updates:
        return JsonResponse(
            {"errors": {"updates": "A non-empty list of updates is required."}}, status=400
        )
    if len(updates) > MAX_REORDER_UPDATES:
        return JsonResponse(
            {
                "errors": {
                    "updates": f"Cannot update more than {MAX_REORDER_UPDATES} blocks at once."
                }
            },
            status=400,
        )
    for index, entry in enumerate(updates):
        if not isinstance(entry, dict):
            return JsonResponse(
                {"errors": {"updates": f"Entry {index} must be an object."}}, status=400
            )
        if not is_plain_int(entry.get("id")):
            return JsonResponse(
                {"errors": {"updates": f"Entry {index} must have an integer 'id'."}}, status=400
            )
    ids = [entry["id"] for entry in updates]
    if len(ids) != len(set(ids)):
        return JsonResponse({"errors": {"updates": "Duplicate block IDs in request."}}, status=400)
    owned_blocks = list(TimeBlock.objects.filter(id__in=ids, schedule__user=request.user))
    if {block.id for block in owned_blocks} != set(ids):
        return JsonResponse({"errors": {"detail": "One or more blocks not found."}}, status=404)
    schedule_ids = {block.schedule_id for block in owned_blocks}
    if len(schedule_ids) != 1:
        return JsonResponse(
            {"errors": {"updates": "All blocks must belong to the same schedule."}}, status=400
        )
    commands = []
    for entry in updates:
        uid = entry["id"]
        for field in ("start_time", "end_time", "sort_order"):
            if field not in entry:
                return JsonResponse(
                    {"errors": {field: f"{field} is required for block {uid}."}}, status=400
                )
        start, error = parse_time_or_error("start_time", entry["start_time"], block_id=uid)
        if error is not None:
            return error
        end, error = parse_time_or_error("end_time", entry["end_time"], block_id=uid)
        if error is not None:
            return error
        _, _, error = validate_block_times(
            entry["start_time"],
            entry["end_time"],
            block_id=uid,
            enforce_granularity=False,
        )
        if error is not None:
            return error
        error = validate_sort_order(entry["sort_order"], block_id=uid)
        if error is not None:
            return error
        commands.append(
            UpdateCommand(uid, start_time=start, end_time=end, sort_order=entry["sort_order"])
        )
    expected_revision = parse_expected_revision(data)
    started = time.monotonic()
    schedule_id = next(iter(schedule_ids))

    def apply(ctx):
        if not set(ids).issubset({block.pk for block in ctx.blocks}):
            return JsonResponse({"errors": {"detail": "One or more blocks not found."}}, status=404)
        window = get_schedule_window(request.user)
        try:
            plan = plan_commands(
                snapshot_from_blocks(ctx.schedule, ctx.blocks),
                (ReorderCommand(tuple(commands)),),
                policy=MANUAL,
                window=window,
            )
        except CommandError as exc:
            return _plan_error_response(
                exc,
                overlap_message="Reorder would cause overlapping blocks.",
                window=window,
                missing_message="One or more blocks not found.",
            )
        persist_command_diff(ctx.schedule, ctx.blocks, plan.diff)
        if plan.diff.updates:
            ctx.schedule.mark_active_on_edit()

    result = execute_schedule_mutation(request.user.pk, schedule_id, expected_revision, apply)
    logger.info("reorder_blocks: %d updates, %.3fs", len(updates), time.monotonic() - started)
    return JsonResponse(result.snapshot)


@login_required
@require_http_methods(["POST"])
@_mutation_errors
def restore_blocks(request, date):
    parsed_date, error = _date_or_error(date)
    if error is not None:
        return error
    data, error = parse_json_object(request)
    if error is not None:
        return error
    entries = data.get("blocks")
    if not isinstance(entries, list):
        return JsonResponse({"errors": {"blocks": "A list of blocks is required."}}, status=400)
    categories = ordered_categories(request.user)
    sink_slug = sink_category(categories).slug
    commands = []
    seen_proof_ids = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return JsonResponse(
                {"errors": {"blocks": f"Entry {index} must be an object."}}, status=400
            )
        title = entry.get("title", "")
        if not isinstance(title, str):
            return JsonResponse(
                {"errors": {"title": f"Title must be a string (block {index})."}}, status=400
            )
        title = title.strip()
        if not title:
            return JsonResponse(
                {"errors": {"title": f"Title is required (block {index})."}}, status=400
            )
        if len(title) > 255:
            return JsonResponse(
                {"errors": {"title": f"Title too long (block {index})."}}, status=400
            )
        start, end, error = _parse_required_times(entry, block_id=index)
        if error is not None:
            return error
        _, _, error = validate_block_times(
            entry["start_time"],
            entry["end_time"],
            block_id=index,
            enforce_granularity=False,
        )
        if error is not None:
            return error
        category = entry.get("category", sink_slug)
        if not isinstance(category, str):
            return JsonResponse(
                {"errors": {"category": f"Category must be a string (block {index})."}}, status=400
            )
        category = validate_slug(category, categories, unknown_to_sink=True)
        completed = entry.get("is_completed", False)
        if not isinstance(completed, bool):
            return JsonResponse(
                {"errors": {"is_completed": f"is_completed must be a boolean (block {index})."}},
                status=400,
            )
        sort_order = entry.get("sort_order", 0)
        error = validate_sort_order(sort_order, block_id=index)
        if error is not None:
            return error
        proof = entry.get("restore_proof")
        if proof is not None and not isinstance(proof, str):
            return JsonResponse(
                {"errors": {"restore_proof": f"Invalid restore proof (block {index})."}},
                status=400,
            )
        block_id = entry.get("id")
        if proof is not None:
            if not is_plain_int(block_id) or block_id <= 0 or block_id in seen_proof_ids:
                return JsonResponse(
                    {"errors": {"id": f"Invalid restore block id (block {index})."}},
                    status=400,
                )
            seen_proof_ids.add(block_id)
        commands.append(
            (CreateCommand(title, start, end, category, completed, sort_order), proof, block_id)
        )
    expected_revision = parse_expected_revision(data)
    started = time.monotonic()

    def apply(ctx):
        fresh = ordered_categories(request.user)
        fresh_commands = []
        for index, (command, proof, block_id) in enumerate(commands):
            origin = TimeBlock.Origin.UNKNOWN
            if proof is not None:
                origin = origin_from_restore_proof(proof, ctx.schedule.id, block_id, command.title)
                if origin is None:
                    return JsonResponse(
                        {"errors": {"restore_proof": f"Invalid restore proof (block {index})."}},
                        status=400,
                    )
            fresh_commands.append(
                CreateCommand(
                    command.title,
                    command.start_time,
                    command.end_time,
                    validate_slug(command.category, fresh, unknown_to_sink=True),
                    command.is_completed,
                    command.sort_order,
                    origin=origin,
                )
            )
        try:
            plan = plan_commands(
                snapshot_from_blocks(ctx.schedule, ctx.blocks),
                (RestoreCommand(tuple(fresh_commands)),),
                policy=UNDO,
            )
        except CommandError as exc:
            return _plan_error_response(exc, overlap_message="Restored blocks would overlap.")
        persist_command_diff(ctx.schedule, ctx.blocks, plan.diff, restore=True)

    result = execute_schedule_mutation(
        request.user.pk, None, expected_revision, apply, date=parsed_date
    )
    logger.info("restore_blocks: %d blocks, %.3fs", len(commands), time.monotonic() - started)
    return JsonResponse(result.snapshot)
