"""AI command endpoint: `POST /api/ai/schedules/<date>/command/`.

Translates a natural-language command into schedule mutations via the
OpenAI-compatible service in ``ai/service.py``, validates and applies each
action atomically, and logs every interaction (success or failure).
"""
import datetime
import functools
import hashlib
import json
import logging

from asgiref.sync import sync_to_async
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
from templates_mgr.models import Rule, Template

from ai.models import AIInteraction
from ai.prompts import DAY_END, DAY_START
from ai.service import (
    AIError,
    AIInvalidInputError,
    AIParseError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
    run_chat,
    run_command,
    run_draft,
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


async def _consume_rate_limit(user_id: int, key_prefix: str, limit: int) -> bool:
    """Increment the per-user fixed-window counter under ``key_prefix``.

    Returns True when the call is within budget (caller proceeds), False
    when exceeded (caller returns 429). ``cache.aadd`` anchors the TTL to
    the first call in each window so it doesn't slide forward on every
    request; falls back to ``cache.aset`` if a backend evicts the key
    mid-window.

    LocMem note: the default ``LocMemCache`` is per-worker, so in
    multi-worker deployments the effective limit is ``limit × workers`` —
    the ``ai.E001`` system check blocks production startup unless the
    cache backend is shared (Redis / Memcached).
    """
    key = f"{key_prefix}:{user_id}"
    if await cache.aadd(key, 1, _RATE_LIMIT_WINDOW_SECONDS):
        count = 1
    else:
        try:
            count = await cache.aincr(key)
        except ValueError:
            await cache.aset(key, 1, _RATE_LIMIT_WINDOW_SECONDS)
            count = 1
    if count > limit:
        logger.warning(
            "AI rate limit exceeded for user %s (key=%s, count=%s, limit=%s)",
            user_id,
            key_prefix,
            count,
            limit,
        )
        return False
    return True


def _rate_limited_response() -> JsonResponse:
    return JsonResponse(
        {"errors": {"detail": "Rate limit exceeded. Try again later."}},
        status=429,
    )


def _rate_limit_per_user(view_func):
    """Fixed-window per-user rate limit decorator for the command endpoint.

    **Async-only** (feature 0009): the wrapper is ``async def`` and
    ``await``s both ``_consume_rate_limit`` and ``view_func``. Applying
    this decorator to a sync view will cause the wrapper's
    ``await view_func(...)`` to raise ``TypeError: object JsonResponse
    can't be used in 'await' expression`` on the first request.
    ``ai_command`` is the only call site and is itself ``async def``.

    Used by ``ai_command``. The draft and chat endpoints do **not** use
    a decorator — their rate limits are consumed inline after
    precondition checks pass, so a 422 / 409 / oversized-body /
    invalid-date does not burn the 10/hr draft or 60/hr chat budgets.
    """
    @functools.wraps(view_func)
    async def wrapper(request, *args, **kwargs):
        # Resolve the authenticated user via the async ORM path. The
        # decorator wrapper executes BEFORE the view body, so it must own
        # the first ``await request.auser()`` — the lazy ``request.user``
        # proxy would otherwise trigger ``SynchronousOnlyOperation`` in
        # an async context. Django caches the resolved user on
        # ``request._acached_user``, so the view body's own
        # ``await request.auser()`` is an ``hasattr`` short-circuit, not
        # a second DB hit.
        user = await request.auser()
        if not await _consume_rate_limit(
            user.id, "ai_cmd_rl", settings.LLM_RATE_LIMIT_PER_HOUR
        ):
            return _rate_limited_response()
        return await view_func(request, *args, **kwargs)
    return wrapper


async def _log_interaction(
    schedule,
    command: str,
    response_text: str,
    actions: list,
    kind: str = AIInteraction.Kind.COMMAND,
) -> AIInteraction | None:
    """Best-effort persistence of one AI interaction. Never raises.

    ``command`` is logged verbatim — pre-strip, pre-validation — so the log
    captures exactly what the client sent. Forensic fidelity matters more
    than cosmetic cleanup here; a malformed or oversized command is what
    we want to see when debugging a model complaint.

    Truncation on ``response_text`` is a belt-and-suspenders safety net for
    pathological provider responses — ``TextField`` has no DB-level max,
    but we don't want a 5 MB hallucination hogging our SQLite file.

    ``kind`` distinguishes user commands from draft generations in audit
    reports without overloading ``user_command`` (drafts log a synthetic
    ``"[DRAFT]"`` placeholder).

    Rows start with ``success=False`` (pessimistic); ``_mark_success`` flips
    them once apply completes.

    A failure to persist the audit row (disk full, DB connection drop) must
    NOT abort the request — otherwise a full disk takes out the whole AI
    feature. Swallow and log so the user still sees their command applied;
    return ``None`` so callers know the row isn't available for later
    ``_mark_success`` updates.
    """
    try:
        return await AIInteraction.objects.acreate(
            schedule=schedule,
            user_command=command[:_MAX_COMMAND_LOG_LEN],
            ai_response=response_text[:_MAX_AI_RESPONSE_LOG_LEN],
            actions_json=actions,
            kind=kind,
        )
    except Exception:
        logger.exception(
            "Failed to persist AIInteraction (schedule=%s)", schedule.id
        )
        return None


async def _mark_success(interaction: AIInteraction | None) -> None:
    """Flip a just-logged AIInteraction row to ``success=True``. No-op if
    the initial log write failed (``interaction is None``)."""
    if interaction is None:
        return
    try:
        interaction.success = True
        await interaction.asave(update_fields=["success"])
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


# ---------------------------------------------------------------------------
# Sync helpers for the mutation atomic blocks. Lifted verbatim out of the
# (now async) views so the ``with transaction.atomic():`` boundary stays
# synchronous — Django 5.2.12 has no ``transaction.aatomic``. The async
# views call these via ``await sync_to_async(_apply_*_sync,
# thread_sensitive=True)(...)``.
#
# The ``_Rollback`` exception-as-control-flow is preserved: a normal
# return from inside ``transaction.atomic()`` commits the partial writes,
# so the only correct way to abort + return is to raise. ``asgiref``'s
# ``SyncToAsync`` re-raises across the thread boundary, so the calling
# async view catches ``_Rollback`` and returns ``rb.response`` unchanged.
# ---------------------------------------------------------------------------


def _apply_actions_sync(schedule, result) -> None:
    """Apply parsed actions under one atomic+select_for_update lock.

    Used by both ``ai_command`` and ``ai_chat`` (the command-style apply
    path). ``_apply_draft_sync`` stays separate because the draft path
    locks the parent ``Schedule`` row and re-checks emptiness — different
    semantics that don't merge cleanly.
    """
    with transaction.atomic():
        locked_blocks = list(
            TimeBlock.objects.filter(schedule=schedule).select_for_update()
        )
        blocks_by_id = {b.id: b for b in locked_blocks}
        for idx, action in enumerate(result.parsed_actions):
            err = _apply_action(schedule, blocks_by_id, action, idx)
            if err is not None:
                raise _Rollback(err)


def _apply_draft_sync(schedule, result) -> None:
    """Apply the AIDraftResult; re-check schedule emptiness under the lock."""
    with transaction.atomic():
        # Lock the SCHEDULE row, not the empty ``TimeBlock`` queryset —
        # see the comment in the original ai_generate_draft for the
        # full rationale.
        Schedule.objects.select_for_update().get(pk=schedule.pk)
        locked_blocks = list(TimeBlock.objects.filter(schedule=schedule))
        if locked_blocks:
            raise _Rollback(
                JsonResponse(
                    {
                        "errors": {
                            "detail": (
                                "Schedule already has blocks; delete "
                                "them before regenerating."
                            )
                        }
                    },
                    status=409,
                )
            )
        blocks_by_id: dict = {}
        for idx, action in enumerate(result.parsed_actions):
            err = _apply_add(schedule, blocks_by_id, action, idx)
            if err is not None:
                raise _Rollback(err)


@login_required
@require_http_methods(["POST"])
@_rate_limit_per_user
async def ai_command(request, date):
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

    # ``await request.auser()`` is cached on ``request._acached_user`` by
    # Django's auth middleware; the decorator wrapper resolved it once
    # already so this call is an ``hasattr`` short-circuit, not a second
    # DB hit. ``request.user`` (the lazy proxy) cannot be touched from
    # an async context without raising ``SynchronousOnlyOperation``.
    user = await request.auser()
    schedule, _ = await Schedule.objects.aget_or_create(user=user, date=parsed_date)
    now = timezone.localtime()

    # Run the LLM call OUTSIDE any transaction — a 15s network call should
    # never hold a DB connection or row locks. The mutation step below
    # re-fetches under ``select_for_update`` and re-validates each action
    # against the locked state, so concurrent edits (delete/insert
    # between the LLM call and the apply step) surface cleanly as 400
    # "block not found" or "overlap" errors.
    current_blocks = [
        b
        async for b in TimeBlock.objects.filter(schedule=schedule).order_by(
            "start_time", "sort_order"
        )
    ]
    # Async view: the await on the LLM client yields the event loop while
    # the network call is in flight. Under WSGI/sync gunicorn this still
    # runs in Django's thread-pool executor (no concurrency win); under
    # an ASGI runner (Phase 7) the worker is freed during the await. See
    # docs/features/0009_async_ai_views_PLAN.md § D5.
    try:
        result = await run_command(command, schedule, current_blocks, now)
    except AIError as e:
        raw = getattr(e, "raw_response_text", "") or str(e)
        await _log_interaction(schedule, command, raw, [])
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
    interaction = await _log_interaction(
        schedule, command, result.raw_response_text, result.parsed_actions
    )

    try:
        await sync_to_async(_apply_actions_sync, thread_sensitive=True)(
            schedule, result
        )
    except _Rollback as rb:
        logger.warning(
            "AI action apply failed (user=%s, schedule=%s, actions=%s)",
            user.id,
            schedule.id,
            len(result.parsed_actions),
        )
        return rb.response

    await _mark_success(interaction)

    # Status flip is gated on actions being non-empty: RULES.md treats a
    # 200 with ``actions: []`` as a successful no-op (LLM ambiguity /
    # out-of-window guard), and undo registration follows the same gate.
    # Promoting a draft to active on a no-op LLM response would lie about
    # user intent.
    if len(result.parsed_actions) > 0:
        await sync_to_async(schedule.mark_active_on_edit, thread_sensitive=True)()

    result_blocks = [
        b
        async for b in TimeBlock.objects.filter(schedule=schedule).order_by(
            "start_time", "sort_order"
        )
    ]
    logger.info(
        "AI command applied (user=%s, schedule=%s, actions=%s)",
        user.id,
        schedule.id,
        len(result.parsed_actions),
    )
    return JsonResponse(
        {
            "blocks": [block_to_dict(b) for b in result_blocks],
            "explanation": result.explanation,
        }
    )


@login_required
@require_http_methods(["POST"])
async def ai_generate_draft(request, date):
    """Generate a draft schedule for an empty day.

    Refuses if the schedule already has any blocks (409) or if the user
    has no template configured for the day's slot type (422). Both checks
    happen before any LLM call **and before the rate-limit counter is
    incremented**, so a stale page or a misconfigured account can't burn
    the 10/hr draft budget without a real LLM call ever firing. (Drafts
    use ``LLM_DRAFT_MODEL``, ~5-10x the cost of ``LLM_MODEL``, so the
    budget is small and worth protecting.)

    The LLM call runs outside any transaction (long network call, no DB
    locks held); the apply step opens a fresh ``transaction.atomic()``
    that **locks the Schedule row** with ``select_for_update()`` (an
    empty ``TimeBlock`` queryset locks zero rows, so the lock has to be
    on the parent), then re-checks emptiness under that lock so a
    concurrent ``create_block`` or another draft request can't race
    blocks in between the pre-call ``exists()`` and the apply.
    """
    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return JsonResponse({"errors": {"date": "Invalid date format."}}, status=400)

    user = await request.auser()
    schedule, _ = await Schedule.objects.aget_or_create(
        user=user, date=parsed_date
    )

    if await TimeBlock.objects.filter(schedule=schedule).aexists():
        return JsonResponse(
            {
                "errors": {
                    "detail": (
                        "Schedule already has blocks; delete them before "
                        "regenerating."
                    )
                }
            },
            status=409,
        )

    slot_type = Template.slot_type_for_date(parsed_date)
    template = await Template.objects.filter(
        user=user, type=slot_type
    ).afirst()
    if template is None:
        return JsonResponse(
            {
                "errors": {
                    "detail": (
                        "No template configured for this day type. "
                        "Open Settings."
                    )
                }
            },
            status=422,
        )

    # Rate limit consumption goes here, AFTER all preconditions pass and
    # BEFORE the LLM call. Earlier 400 / 409 / 413 / 422 paths must not
    # increment the counter — see the docstring above.
    if not await _consume_rate_limit(
        user.id,
        "ai_draft_rl",
        settings.LLM_DRAFT_RATE_LIMIT_PER_HOUR,
    ):
        return _rate_limited_response()

    history_start = parsed_date - datetime.timedelta(
        days=settings.LLM_HISTORY_DAYS
    )
    history = [
        s
        async for s in Schedule.objects.filter(
            user=user,
            date__lt=parsed_date,
            date__gte=history_start,
            status__in=[Schedule.Status.ACTIVE, Schedule.Status.REVIEWED],
        )
        .order_by("date")
        # ``prompts.build_draft_user_message`` reads ``past.daily_review``
        # for each schedule (Phase-6 completion-ratio suffix). Without
        # ``select_related`` that's an N+1 — one extra query per past
        # day. ``async for`` honours ``select_related`` /
        # ``prefetch_related`` identically to sync iteration.
        .select_related("daily_review")
        .prefetch_related("time_blocks")
    ]
    rules = [
        r
        async for r in Rule.objects.filter(user=user, is_active=True).order_by(
            "-priority"
        )
    ]

    now = timezone.localtime()
    try:
        result = await run_draft(schedule, template, history, rules, now)
    except AIError as e:
        raw = getattr(e, "raw_response_text", "") or str(e)
        await _log_interaction(
            schedule, "[DRAFT]", raw, [], kind=AIInteraction.Kind.DRAFT
        )
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

    interaction = await _log_interaction(
        schedule,
        "[DRAFT]",
        result.raw_response_text,
        result.parsed_actions,
        kind=AIInteraction.Kind.DRAFT,
    )

    try:
        await sync_to_async(_apply_draft_sync, thread_sensitive=True)(
            schedule, result
        )
    except _Rollback as rb:
        logger.warning(
            "AI draft apply failed (user=%s, schedule=%s, actions=%s)",
            user.id,
            schedule.id,
            len(result.parsed_actions),
        )
        return rb.response

    await _mark_success(interaction)

    # Drafts intentionally do NOT flip ``schedule.status``. The badge
    # stays "draft" until the user makes a real edit (which happens
    # through one of the forward-mutating endpoints in schedules.api).
    result_blocks = [
        b
        async for b in TimeBlock.objects.filter(schedule=schedule).order_by(
            "start_time", "sort_order"
        )
    ]
    logger.info(
        "AI draft applied (user=%s, schedule=%s, actions=%s)",
        user.id,
        schedule.id,
        len(result.parsed_actions),
    )
    return JsonResponse(
        {
            "blocks": [block_to_dict(b) for b in result_blocks],
            "explanation": result.explanation,
        }
    )


# ---------------------------------------------------------------------------
# Chat (feature 0007): multi-turn AI conversation.
# ---------------------------------------------------------------------------


def _validate_chat_messages(messages) -> str | None:
    """Return an error string if ``messages`` is malformed, else ``None``.

    Validation order matters: this runs BEFORE ``Schedule.get_or_create``
    AND BEFORE the rate-limit token is consumed, so a bad body cannot
    create an empty Schedule row or burn the user's budget.
    """
    if not isinstance(messages, list):
        return "messages must be an array"
    n = len(messages)
    if n < 1:
        return "messages must contain at least one entry"
    if n > settings.LLM_CHAT_MAX_TURNS:
        return f"too many messages (max {settings.LLM_CHAT_MAX_TURNS})"

    total_chars = 0
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            return f"messages[{idx}] must be an object"
        role = msg.get("role")
        if role not in ("user", "assistant"):
            return f"messages[{idx}].role must be 'user' or 'assistant'"
        content = msg.get("content")
        if not isinstance(content, str):
            return f"messages[{idx}].content must be a string"
        if len(content) < 1:
            return f"messages[{idx}].content cannot be empty"
        if len(content) > settings.LLM_MAX_COMMAND_CHARS:
            return (
                f"messages[{idx}].content too long "
                f"(max {settings.LLM_MAX_COMMAND_CHARS} chars)"
            )
        total_chars += len(content)
        # Roles strictly alternate, starting with user.
        expected = "user" if idx % 2 == 0 else "assistant"
        if role != expected:
            return (
                f"messages[{idx}].role must be {expected!r} "
                f"(roles must strictly alternate user/assistant)"
            )

    if total_chars > settings.LLM_CHAT_MAX_TOTAL_CHARS:
        return (
            f"total content too long ({total_chars} > "
            f"{settings.LLM_CHAT_MAX_TOTAL_CHARS} chars)"
        )

    if messages[-1]["role"] != "user":
        return "messages must end with a user turn"

    return None


def _transcript_sha256(messages) -> str:
    """Stable hash of the client-supplied transcript for audit rows.

    Uses ``sort_keys=True`` and ``ensure_ascii=False`` so the hash is
    invariant under JSON re-encoding but does NOT collapse unicode
    differently than the wire form (we want the hash to match what the
    client actually sent, which is ``ensure_ascii=False`` after our
    server's ``json.loads``).
    """
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_chat_audit_response(messages, raw_or_str: str, error_class: str | None) -> str:
    """Build the JSON-encoded ``ai_response`` payload for a chat audit row.

    Same shape for success and failure rows; ``error_class`` is ``None``
    for success and the exception class name for failure. Both rows
    carry the transcript hash so a future audit can group rows that
    belong to the same client-supplied transcript.
    """
    payload = {
        "transcript_sha256": _transcript_sha256(messages),
        "turn_count": len(messages),
        "raw": raw_or_str,
    }
    if error_class is not None:
        payload["error_class"] = error_class
    return json.dumps(payload, ensure_ascii=False)


async def _log_chat_failure(schedule, last_user_msg: str, messages, exc) -> None:
    """Persist the failure-row variant of the chat audit envelope."""
    raw = getattr(exc, "raw_response_text", "") or str(exc)
    payload = _build_chat_audit_response(
        messages, raw, error_class=type(exc).__name__
    )
    await _log_interaction(schedule, last_user_msg, payload, [])


@login_required
@require_http_methods(["POST"])
async def ai_chat(request, date):
    """Multi-turn chat endpoint (feature 0007).

    Validation order is deliberate (matches ``ai_generate_draft`` for
    rate-limit safety, plus message validation BEFORE ``get_or_create``
    so a malformed request can't auto-create an empty ``Schedule`` row):

      1. Reject oversized body.
      2. Parse + validate the URL date.
      3. Parse JSON body.
      4. Validate ``messages[]`` (length, roles, alternation, content
         caps). Bad body returns 400 BEFORE any DB write or rate-limit
         consumption.
      5. ``Schedule.get_or_create``.
      6. Consume the chat rate-limit token.
      7. Snapshot blocks (no transaction — LLM call must not hold locks).
      8. ``run_chat`` outside any transaction.
      9. Audit-log this turn (success-row variant; failure-row was
         logged in the ``except AIError`` branch).
     10. Apply actions atomically if any, OR return clarifying-question
         payload, OR return chit-chat (empty actions + null ask).
    """
    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return JsonResponse(
            {"errors": {"date": "Invalid date format."}}, status=400
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"errors": {"body": "Invalid JSON."}}, status=400
        )
    # Non-object JSON roots (``[]``, ``"x"``, ``123``, ``null``) parse
    # fine but break ``data.get(...)`` with AttributeError → 500. Reject
    # them as 400 here so the contract from the planning doc holds:
    # any malformed body returns 4xx, never 5xx.
    if not isinstance(data, dict):
        return JsonResponse(
            {"errors": {"body": "Request body must be a JSON object."}},
            status=400,
        )

    messages = data.get("messages")
    err = _validate_chat_messages(messages)
    if err is not None:
        return JsonResponse({"errors": {"messages": err}}, status=400)

    user = await request.auser()
    schedule, _ = await Schedule.objects.aget_or_create(
        user=user, date=parsed_date
    )

    if not await _consume_rate_limit(
        user.id, "ai_chat_rl", settings.LLM_CHAT_RATE_LIMIT_PER_HOUR
    ):
        return _rate_limited_response()

    last_user_msg = messages[-1]["content"]

    current_blocks = [
        b
        async for b in TimeBlock.objects.filter(schedule=schedule).order_by(
            "start_time", "sort_order"
        )
    ]
    now = timezone.localtime()

    try:
        result = await run_chat(messages, schedule, current_blocks, now)
    except AIError as e:
        await _log_chat_failure(schedule, last_user_msg, messages, e)
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

    audit_response = _build_chat_audit_response(
        messages, result.raw_response_text, error_class=None
    )
    interaction = await _log_interaction(
        schedule, last_user_msg, audit_response, result.parsed_actions
    )

    # Clarifying-question turn — no mutations, no schedule status flip.
    if result.ask is not None:
        await _mark_success(interaction)
        return JsonResponse(
            {
                "blocks": None,
                "explanation": result.explanation,
                "ask": result.ask,
                "applied": False,
            }
        )

    # Chit-chat / "thanks" turn — empty actions and null ask.
    if not result.parsed_actions:
        await _mark_success(interaction)
        return JsonResponse(
            {
                "blocks": None,
                "explanation": result.explanation,
                "ask": None,
                "applied": False,
            }
        )

    # Apply path: same select_for_update + per-action dispatcher as
    # ai_command. Re-fetches under the lock so a concurrent edit between
    # the LLM call and the apply surfaces as a clean per-action error.
    try:
        await sync_to_async(_apply_actions_sync, thread_sensitive=True)(
            schedule, result
        )
    except _Rollback as rb:
        logger.warning(
            "AI chat apply failed (user=%s, schedule=%s, actions=%s)",
            user.id,
            schedule.id,
            len(result.parsed_actions),
        )
        return rb.response

    await _mark_success(interaction)
    await sync_to_async(schedule.mark_active_on_edit, thread_sensitive=True)()

    result_blocks = [
        b
        async for b in TimeBlock.objects.filter(schedule=schedule).order_by(
            "start_time", "sort_order"
        )
    ]
    logger.info(
        "AI chat applied (user=%s, schedule=%s, actions=%s)",
        user.id,
        schedule.id,
        len(result.parsed_actions),
    )
    return JsonResponse(
        {
            "blocks": [block_to_dict(b) for b in result_blocks],
            "explanation": result.explanation,
            "ask": None,
            "applied": True,
        }
    )
