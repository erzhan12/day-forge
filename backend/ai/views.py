"""AI command endpoint: `POST /api/ai/schedules/<date>/command/`.

Translates a natural-language command into schedule mutations via the
OpenAI-compatible service in ``ai/service.py``, validates and applies each
action atomically, and logs every interaction (success or failure).
"""
import datetime
import functools
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from schedules.http import (
    VALID_CATEGORIES,
    block_to_dict,
    parse_time,
    reject_oversized_body,
    times_overlap,
)
from schedules.models import Schedule, TimeBlock
from schedules.validators import validate_five_minute_granularity

from ai.models import AIInteraction
from ai.prompts import DAY_END, DAY_START
from ai.service import (
    AIError,
    AIInvalidInputError,
    AIParseError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
    run_command,
)

_DAY_START_T = datetime.time.fromisoformat(DAY_START)
_DAY_END_T = datetime.time.fromisoformat(DAY_END)

logger = logging.getLogger(__name__)

_AI_ERROR_STATUS = {
    AIUnavailableError: 503,
    AIInvalidInputError: 400,
    AITimeoutError: 504,
    AIProviderError: 502,
    AIParseError: 502,
}

_MAX_AI_RESPONSE_LOG_LEN = 10_000
# Cap logged user commands so a mis-sized request (over the 1 MB body cap in
# ``reject_oversized_body`` but still within it) can't bloat the audit
# table. Kept strictly larger than ``LLM_MAX_COMMAND_CHARS`` so the log
# preserves evidence that the user *exceeded* the per-request cap.
_MAX_COMMAND_LOG_LEN = 2_000

_RATE_LIMIT_WINDOW_SECONDS = 3600


def _rate_limit_per_user(view_func):
    """Fixed-window per-user rate limit via Django's default cache.

    Budget is ``settings.LLM_RATE_LIMIT_PER_HOUR`` calls per user per hour;
    over-budget requests return 429. ``cache.add`` + ``cache.incr`` anchors
    the TTL to the first call in each window instead of sliding it forward
    on every request. The default LocMem cache is per-worker, so in
    multi-worker deployments the effective limit is ``limit × workers`` —
    use a shared cache backend (e.g. Redis) for an accurate global count.
    """
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        key = f"ai_cmd_rl:{request.user.id}"
        if cache.add(key, 1, _RATE_LIMIT_WINDOW_SECONDS):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, _RATE_LIMIT_WINDOW_SECONDS)
                count = 1
        if count > settings.LLM_RATE_LIMIT_PER_HOUR:
            logger.warning(
                "AI rate limit exceeded for user %s (count=%s, limit=%s)",
                request.user.id,
                count,
                settings.LLM_RATE_LIMIT_PER_HOUR,
            )
            return JsonResponse(
                {"errors": {"detail": "Rate limit exceeded. Try again later."}},
                status=429,
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def _log_interaction(
    schedule,
    command: str,
    response_text: str,
    actions: list,
) -> AIInteraction | None:
    """Best-effort persistence of one AI interaction. Never raises.

    ``command`` is logged verbatim — pre-strip, pre-validation — so the log
    captures exactly what the client sent. Forensic fidelity matters more
    than cosmetic cleanup here; a malformed or oversized command is what
    we want to see when debugging a model complaint.

    Truncation on ``response_text`` is a belt-and-suspenders safety net for
    pathological provider responses — ``TextField`` has no DB-level max,
    but we don't want a 5 MB hallucination hogging our SQLite file.

    Rows start with ``success=False`` (pessimistic); ``_mark_success`` flips
    them once apply completes.

    A failure to persist the audit row (disk full, DB connection drop) must
    NOT abort the request — otherwise a full disk takes out the whole AI
    feature. Swallow and log so the user still sees their command applied;
    return ``None`` so callers know the row isn't available for later
    ``_mark_success`` updates.
    """
    try:
        return AIInteraction.objects.create(
            schedule=schedule,
            user_command=command[:_MAX_COMMAND_LOG_LEN],
            ai_response=response_text[:_MAX_AI_RESPONSE_LOG_LEN],
            actions_json=actions,
        )
    except Exception:
        logger.exception(
            "Failed to persist AIInteraction (schedule=%s)", schedule.id
        )
        return None


def _mark_success(interaction: AIInteraction | None) -> None:
    """Flip a just-logged AIInteraction row to ``success=True``. No-op if
    the initial log write failed (``interaction is None``)."""
    if interaction is None:
        return
    try:
        interaction.success = True
        interaction.save(update_fields=["success"])
    except Exception:
        logger.exception(
            "Failed to mark AIInteraction success (id=%s)", interaction.id
        )


class _Rollback(Exception):
    """Carries the ``JsonResponse`` to return after rolling back mutations.

    Raised from inside ``transaction.atomic()`` so Django unwinds the
    transaction; the outer ``except`` returns the stashed response.
    """

    def __init__(self, response: JsonResponse):
        self.response = response


def _action_error(action_index: int, detail, status: int = 400) -> JsonResponse:
    return JsonResponse(
        {"errors": {"action_index": action_index, "detail": detail}},
        status=status,
    )


def _validation_error_detail(e: ValidationError) -> dict:
    """Return the richest available detail from a ``ValidationError``.

    ``message_dict`` only exists when the error was constructed with
    per-field data (typically via ``full_clean``). A bare
    ``ValidationError("msg")`` has no ``message_dict`` and accessing it
    would raise ``AttributeError``. Fall back to ``str(e)`` so a future
    model-validator refactor can't produce a cryptic 500.
    """
    return getattr(e, "message_dict", None) or {"detail": str(e)}


def _check_day_window(action_index: int, start, end) -> JsonResponse | None:
    """Reject times outside the ``[DAY_START, DAY_END]`` working-day window.

    Mirrors the frontend guard in ``useDrag.ts`` and the constraint the
    system prompt asks the model to respect — enforced here so a
    hallucinating response can't insert off-window blocks.
    """
    if start < _DAY_START_T:
        return _action_error(
            action_index, f"start_time must be >= {DAY_START}"
        )
    if end > _DAY_END_T:
        return _action_error(
            action_index, f"end_time must be <= {DAY_END}"
        )
    return None


def _check_granularity(action_index: int, *times) -> JsonResponse | None:
    """Run the 5-minute granularity validator and map ``ValidationError`` to
    the action-index error envelope."""
    try:
        for t in times:
            validate_five_minute_granularity(t)
    except ValidationError as e:
        return _action_error(action_index, str(e.message))
    return None


def _check_no_overlap(
    blocks_by_id, start, end, exclude_id, action_index: int
) -> JsonResponse | None:
    """Reject the action if its ``[start, end)`` window overlaps any block
    in ``blocks_by_id`` other than ``exclude_id`` (pass ``None`` to scan
    everything)."""
    for other_id, other in blocks_by_id.items():
        if other_id == exclude_id:
            continue
        if times_overlap(other.start_time, other.end_time, start, end):
            return _action_error(action_index, "block would overlap existing block")
    return None


def _apply_add(
    schedule, blocks_by_id, action, action_index: int
) -> JsonResponse | None:
    title = action["title"].strip()
    # ``category`` is required by ``schemas.validate_action_shape``; the
    # ``get(..., "other")`` fallback is defence-in-depth if the schema check
    # is ever relaxed or bypassed.
    category = action.get("category", "other")
    if category not in VALID_CATEGORIES:
        return _action_error(action_index, f"invalid category {category!r}")
    start = parse_time(action["start_time"])
    end = parse_time(action["end_time"])

    err = _check_day_window(action_index, start, end)
    if err is not None:
        return err
    err = _check_granularity(action_index, start, end)
    if err is not None:
        return err
    if start >= end:
        return _action_error(action_index, "start_time must be < end_time")
    err = _check_no_overlap(blocks_by_id, start, end, None, action_index)
    if err is not None:
        return err

    max_sort = max((b.sort_order for b in blocks_by_id.values()), default=-1)
    block = TimeBlock(
        schedule=schedule,
        title=title,
        start_time=start,
        end_time=end,
        category=category,
        sort_order=max_sort + 1,
    )
    try:
        block.full_clean()
    except ValidationError as e:
        return _action_error(action_index, _validation_error_detail(e))
    block.save()
    blocks_by_id[block.id] = block
    return None


def _apply_remove(
    schedule, blocks_by_id, action, action_index: int, block
) -> JsonResponse | None:
    block.delete()
    blocks_by_id.pop(block.id, None)
    return None


def _compute_move_resize_times(action, block):
    """Resolve the effective ``(new_start, new_end)`` for a move/resize
    action and flag a midnight wrap.

    Returns ``(new_start, new_end, wrapped_past_midnight)``.
    """
    kind = action["type"]
    new_start = parse_time(action["start_time"]) if "start_time" in action else block.start_time
    new_end = parse_time(action["end_time"]) if "end_time" in action else block.end_time

    if kind == "move" and "end_time" not in action:
        # Preserve original duration for bare "move to HH:MM" commands.
        original = (
            datetime.datetime.combine(datetime.date.min, block.end_time)
            - datetime.datetime.combine(datetime.date.min, block.start_time)
        )
        new_end = (
            datetime.datetime.combine(datetime.date.min, new_start) + original
        ).time()
        # ``.time()`` silently wraps if the duration crosses midnight
        # (e.g. moving a 22:00-23:30 block to 23:00 would yield 00:30).
        if new_end <= new_start:
            return new_start, new_end, True

    return new_start, new_end, False


def _apply_move_or_resize(
    schedule, blocks_by_id, action, action_index: int, block
) -> JsonResponse | None:
    new_start, new_end, wrapped = _compute_move_resize_times(action, block)
    if wrapped:
        return _action_error(
            action_index, "moved block would extend past midnight"
        )

    err = _check_day_window(action_index, new_start, new_end)
    if err is not None:
        return err
    err = _check_granularity(action_index, new_start, new_end)
    if err is not None:
        return err
    if new_start >= new_end:
        return _action_error(action_index, "start_time must be < end_time")
    err = _check_no_overlap(
        blocks_by_id, new_start, new_end, block.id, action_index
    )
    if err is not None:
        return err

    block.start_time = new_start
    block.end_time = new_end
    try:
        block.full_clean()
    except ValidationError as e:
        return _action_error(action_index, _validation_error_detail(e))
    block.save()
    return None


def _apply_existing_block_action(
    schedule, blocks_by_id, action, action_index: int
) -> JsonResponse | None:
    """Dispatcher for move / remove / resize — all need an existing block."""
    task_id = action["task_id"]
    block = blocks_by_id.get(task_id)
    if block is None:
        # 400 (not 404) to avoid id enumeration across users / schedules.
        # ``blocks_by_id`` is built from the select_for_update re-fetch, so a
        # miss here means the LLM referenced an id that either never existed
        # on this schedule or was deleted between the LLM call and the apply
        # step — surface both as the same "no longer exists" message.
        return _action_error(
            action_index,
            "Referenced block no longer exists; it may have been "
            "deleted. Please retry.",
        )
    if action["type"] == "remove":
        return _apply_remove(schedule, blocks_by_id, action, action_index, block)
    return _apply_move_or_resize(
        schedule, blocks_by_id, action, action_index, block
    )


_ACTION_DISPATCH = {
    "add": _apply_add,
    "move": _apply_existing_block_action,
    "remove": _apply_existing_block_action,
    "resize": _apply_existing_block_action,
}


def _apply_action(
    schedule, blocks_by_id, action, action_index: int
) -> JsonResponse | None:
    """Apply one AI action; return ``None`` on success or a 400 response.

    Called sequentially under the schedule's row lock. Overlap checks use
    the in-memory ``blocks_by_id`` so a batch like ``[remove X, add Y at
    same slot]`` works without a spurious overlap error.
    """
    handler = _ACTION_DISPATCH[action["type"]]
    return handler(schedule, blocks_by_id, action, action_index)


@login_required
@require_http_methods(["POST"])
@_rate_limit_per_user
def ai_command(request, date):
    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return JsonResponse({"errors": {"date": "Invalid date format."}}, status=400)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"errors": {"body": "Invalid JSON."}}, status=400)

    command = data.get("command")
    if not isinstance(command, str):
        return JsonResponse({"errors": {"command": "command must be a string."}}, status=400)

    schedule, _ = Schedule.objects.get_or_create(user=request.user, date=parsed_date)
    now = timezone.localtime()

    # Run the LLM call OUTSIDE any transaction — a 15s network call should
    # never hold a DB connection or row locks. The mutation step below
    # re-fetches under ``select_for_update`` and re-validates each action
    # against the locked state, so concurrent edits (delete/insert
    # between the LLM call and the apply step) surface cleanly as 400
    # "block not found" or "overlap" errors.
    current_blocks = list(
        TimeBlock.objects.filter(schedule=schedule).order_by("start_time", "sort_order")
    )
    try:
        result = run_command(command, schedule, current_blocks, now)
    except AIError as e:
        raw = getattr(e, "raw_response_text", "") or str(e)
        _log_interaction(schedule, command, raw, [])
        # Walk MRO so a future subclass (e.g. ``AIRateLimitError``) resolves
        # to its parent's status instead of raising ``KeyError``. If a new
        # AIError subclass is ever added with no mapped parent, fall back to
        # 500 and log loudly — that's a programming error we want visible.
        status = next(
            (s for cls, s in _AI_ERROR_STATUS.items() if isinstance(e, cls)),
            None,
        )
        if status is None:
            logger.error(
                "Unmapped AIError subclass %s — add to _AI_ERROR_STATUS",
                type(e).__name__,
            )
            status = 500
        return JsonResponse({"errors": {"detail": str(e)}}, status=status)

    # Intent log BEFORE applying actions. Persisted outside the mutation
    # atomic so it survives a mid-batch rollback — PRD §6.5 requires every
    # interaction to be logged. Row starts pessimistic (``success=False``)
    # and is flipped to True post-apply via ``_mark_success``.
    interaction = _log_interaction(
        schedule, command, result.raw_response_text, result.parsed_actions
    )

    try:
        with transaction.atomic():
            locked_blocks = list(
                TimeBlock.objects.filter(schedule=schedule).select_for_update()
            )
            blocks_by_id = {b.id: b for b in locked_blocks}
            for idx, action in enumerate(result.parsed_actions):
                err = _apply_action(schedule, blocks_by_id, action, idx)
                if err is not None:
                    raise _Rollback(err)
    except _Rollback as rb:
        logger.warning(
            "AI action apply failed (user=%s, schedule=%s, actions=%s)",
            request.user.id,
            schedule.id,
            len(result.parsed_actions),
        )
        return rb.response

    _mark_success(interaction)

    result_blocks = TimeBlock.objects.filter(schedule=schedule).order_by(
        "start_time", "sort_order"
    )
    logger.info(
        "AI command applied (user=%s, schedule=%s, actions=%s)",
        request.user.id,
        schedule.id,
        len(result.parsed_actions),
    )
    return JsonResponse(
        {
            "blocks": [block_to_dict(b) for b in result_blocks],
            "explanation": result.explanation,
        }
    )
