"""AI draft and chat endpoints with atomic schedule mutation helpers."""

import datetime
import hashlib
import json
import logging
from dataclasses import replace

from asgiref.sync import sync_to_async
from common.http import parse_json_object, reject_oversized_body
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from schedules.categories import ordered_categories, serialize_category
from schedules.commands import CreateCommand, MutationDiff
from schedules.models import Category, Schedule, TimeBlock
from schedules.mutations import (
    MutationRejected,
    ScheduleChanged,
    execute_schedule_mutation,
    parse_expected_revision,
    run_user_maintenance,
    schedule_changed_response,
)
from schedules.persistence import PersistenceError, persist_command_diff
from schedules.planning import DRAFT, CommandError, plan_commands, snapshot_from_blocks
from schedules.ratelimit import consume_rate_limit, rate_limited_response
from schedules.time_validation import parse_time
from schedules.window import (
    ScheduleWindow,
    get_schedule_settings,
    resolve_time_zone,
)
from templates_mgr.models import Rule, Template

from ai.category_resolution import UnresolvedCategory
from ai.chat_requests import ChatClaim, claim_request, finish_request, request_identity
from ai.free_slot import GRID_MINUTES
from ai.models import AIInteraction
from ai.mutation_planner import (
    ActionOutcome,
    PlanError,
    action_outcome_to_dict,
    compute_apply_context_fingerprint,
    plan_mutations,
)
from ai.relative_add_guard import relative_add_guard_ask
from ai.replay_guard import (
    GUARD_EXPLANATION,
    REPLAY_GUARD_REASON_CODE,
    build_guard_ask,
    find_replayed_actions,
    truncate_title,
)
from ai.schemas import MAX_ACTIONS_PER_COMMAND
from ai.service import (
    AIChatResult,
    AIDraftResult,
    AIError,
    AIInvalidInputError,
    AIParseError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
    run_chat,
    run_draft,
)

logger = logging.getLogger(__name__)


def _safe_block_title(block) -> str:
    return block.title if block.origin == TimeBlock.Origin.MANUAL else "[private block]"

_AI_ERROR_STATUS = {
    AIUnavailableError: 503,
    AIInvalidInputError: 400,
    AITimeoutError: 504,
    AIProviderError: 502,
    AIParseError: 502,
}

_MAX_AI_RESPONSE_LOG_LEN = 10_000
# Cap logged user commands so a request within the 100 KB body cap cannot
# bloat the audit table. Kept larger than ``LLM_MAX_COMMAND_CHARS`` so the log
# preserves evidence that the user *exceeded* the per-request cap.
_MAX_COMMAND_LOG_LEN = 2_000

# Feature 0084 (issue #209): a generic, user-facing 502 message for every
# ``AIParseError`` — the real validation string (which can echo raw
# model-supplied text, e.g. an unresolved category label or an unknown JSON
# key) goes only to the chat audit row's ``error_detail`` or the draft
# server log, never to the client. Every other ``AIError`` subclass keeps
# ``str(e)`` as its user-facing detail, unchanged.
AI_PARSE_ERROR_DETAIL = "The assistant's reply couldn't be applied. Try rephrasing."

# Cap on the chat audit row's ``error_detail`` (the ``AIParseError`` message,
# NOT the raw provider response, which already has its own cap above).
# A pragmatic size cap, not a bound: a 20-action error list can exceed it,
# in which case the tail is cut (the full model output is still in ``raw``).
_MAX_ERROR_DETAIL_LEN = 2_000


async def _consume_rate_limit(user_id: int, key_prefix: str, limit: int) -> bool:
    """Consume an AI bucket token through the shared synchronous limiter."""
    key = f"{key_prefix}:{user_id}"
    return await sync_to_async(consume_rate_limit, thread_sensitive=True)(key, limit)


async def _log_interaction(
    schedule: Schedule,
    command: str,
    response_text: str,
    actions: list[dict],
    kind: str = AIInteraction.Kind.CHAT,
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
        logger.exception("Failed to persist AIInteraction (schedule=%s)", schedule.id)
        return None


async def _mark_success(
    interaction: AIInteraction | None, outcomes: list[dict] | None = None
) -> None:
    """Flip a just-logged AIInteraction row to ``success=True``. No-op if
    the initial log write failed (``interaction is None``)."""
    if interaction is None:
        return
    try:
        interaction.success = True
        update_fields = ["success"]
        if outcomes is not None:
            interaction.outcomes_json = outcomes
            update_fields.append("outcomes_json")
        await interaction.asave(update_fields=update_fields)
    except Exception:
        logger.exception("Failed to mark AIInteraction success (id=%s)", interaction.id)


class _Rollback(Exception):
    """Carries the ``JsonResponse`` to return after rolling back mutations.

    Raised from inside ``transaction.atomic()`` so Django unwinds the
    transaction; the outer ``except`` returns the stashed response.
    """

    def __init__(self, response: JsonResponse):
        self.response = response


def _action_error(action_index: int, detail: str | dict) -> JsonResponse:
    return JsonResponse(
        {"errors": {"action_index": action_index, "detail": detail}},
        status=400,
    )


def _build_resolution_ask(
    outcomes: tuple[ActionOutcome, ...],
    block_titles: dict[int, str],
    create_titles: dict[int, str],
) -> str | None:
    """Return one concise server-owned follow-up for skipped time work."""
    skipped = [outcome for outcome in outcomes if outcome.skipped_fields]
    if not skipped:
        return None

    def title(outcome: ActionOutcome) -> str:
        return block_titles.get(
            outcome.task_id, create_titles.get(outcome.action_index, "That block")
        )

    def title_for_id(block_id: int) -> str:
        return block_titles.get(block_id, "that block")

    # Resolve by fixed precedence, scanning ALL skipped outcomes so the
    # question the user sees is order-invariant (not whichever skipped
    # outcome happened to appear first). Precedence:
    #   concrete suggestion > direction_required > unresolved_conflict
    #   > attempted_direction(no free later/earlier slot for a move)
    #   > no_slot(auto-placement has no forward slot) > out_of_window
    #   > skipped-add(task_id None) > generic-invalid.
    for outcome in skipped:
        suggestion = outcome.suggestion
        if (
            suggestion
            and not suggestion.direction_required
            and suggestion.start_time
            and suggestion.end_time
        ):
            return (
                f"{title(outcome)} conflicts at that time. Move it to "
                f"{suggestion.start_time:%H:%M}–{suggestion.end_time:%H:%M}?"
            )
    for outcome in skipped:
        if outcome.suggestion and outcome.suggestion.direction_required:
            return "That time conflicts. Should I look for an earlier or later slot?"
    for outcome in skipped:
        if outcome.reason_code == "unresolved_conflict":
            others = [title_for_id(cid) for cid in outcome.conflicting_task_ids]
            names = [title(outcome), *others]
            if len(names) >= 2:
                joined = f"'{names[0]}' and '{names[1]}'"
                return f"{joined} can't both move to that time. Which should move?"
            return "Those requested moves conflict with each other. Which one should move?"
    for outcome in skipped:
        if outcome.attempted_direction in {"later", "earlier"}:
            return (
                f"No free {outcome.attempted_direction} slot fits {title(outcome)} "
                "within your day window. Please choose another time."
            )
    # Feature 0067: an untimed auto-placed add that found no forward slot. A
    # ``no_slot`` outcome has ``task_id is None`` and empty ``attempted_direction``,
    # so this must precede the generic skipped-add branch below (which would
    # otherwise emit the wrong "give it a concrete free start/end" copy).
    for outcome in skipped:
        if outcome.reason_code == "no_slot":
            return (
                f"No free slot with the required gaps fits {title(outcome)} in your "
                "day window. Try a shorter duration or a specific free time."
            )
    for outcome in skipped:
        if outcome.reason_code == "out_of_window":
            return "That time is outside your schedule window. Please give a time within your day."
    for outcome in skipped:
        if outcome.task_id is None:
            return (
                f"{title(outcome)} does not fit at that time. Please give it a "
                "concrete free start and end time."
            )
    # ``skipped`` is guaranteed non-empty (the early ``if not skipped`` guard),
    # so fall back to the first outcome's generic message.
    return (
        f"That time range for {title(skipped[0])} is not valid or available. "
        "Please give a valid time."
    )


def _build_category_ask(
    unresolved: tuple[UnresolvedCategory, ...],
    block_titles: dict[int, str],
    categories: list[Category],
) -> str | None:
    """Server-owned follow-up for an ``update`` dropped for its category
    (feature 0084, issue #209). English-only, like ``_build_resolution_ask``
    and ``build_guard_ask`` — see RULES.md.

    Only the FIRST unresolved record is asked about (accepted precedent —
    same "first of several" choice ``_build_resolution_ask`` makes). The
    rejected value itself never appears here: the audit row's ``raw``
    already holds it, and this is a user-facing string.
    """
    if not unresolved or not categories:
        return None
    record = unresolved[0]
    title = block_titles.get(record.task_id, "that block")
    labels = ", ".join(category.label for category in categories)
    return f'Which category should "{truncate_title(title)}" use: {labels}?'


def _replay_guard_response(
    interaction: AIInteraction | None,
    parsed_actions: list[dict],
    offending: tuple[int, ...],
    *,
    user_id: int,
    schedule_id: int,
    snapshot: dict,
) -> JsonResponse:
    """Build the 200 response for a tripped replay guard (feature 0083).

    All-or-nothing: every parsed action from this turn is skipped, not just
    the offending ``add``(s) — a sibling move/remove/resize/update in the
    same model output is just as suspect once the model has proven it
    misread the latest turn. See ``docs/features/0083_PLAN.md`` §B3.
    """
    outcomes = [
        ActionOutcome(
            action_index=idx,
            task_id=action.get("task_id") if action.get("type") != "add" else None,
            status="skipped",
            skipped_fields=("title", "category", "start_time", "end_time")
            if action.get("type") == "add"
            else (),
            reason_code=REPLAY_GUARD_REASON_CODE,
        )
        for idx, action in enumerate(parsed_actions)
    ]
    outcome_payload = [action_outcome_to_dict(o) for o in outcomes]
    logger.warning(
        "AI chat replay guard tripped (user=%s, schedule=%s, interaction=%s, actions=%s)",
        user_id,
        schedule_id,
        interaction.id if interaction else None,
        offending,
    )
    first_title = parsed_actions[offending[0]].get("title", "")
    return JsonResponse(
        {
            **snapshot,
            "blocks": None,
            "explanation": GUARD_EXPLANATION,
            "ask": build_guard_ask(first_title),
            "applied": False,
            "partial": False,
            "outcomes": outcome_payload,
        }
    )


def _earliest_start(
    schedule_date: datetime.date,
    window: ScheduleWindow,
    now_local: datetime.datetime,
) -> datetime.time | None:
    """Compute the forward placement floor for chat auto-placement (feature 0067).

    - Non-today schedule (``schedule_date != now_local.date()``) → ``None``: the
      planner then searches from ``window.day_start`` independent of the clock.
    - Today → the current local time rounded **UP** to the next 5-min grid
      (an exact grid instant is unchanged; any leftover seconds/microseconds
      round up so the block never lands in the past). Then:
        * If the rounded value would cross midnight, or ``now`` is at/after the
          window end, return ``window.day_end`` — a no-fit sentinel that makes
          ``plan_mutations`` deterministically emit ``no_slot`` (base_min ==
          end_minutes ⇒ base_min + dur > end_minutes for any positive dur).
        * If the rounded value is before the window start, return
          ``window.day_start``.
        * Otherwise return the rounded grid time.
    """
    if schedule_date != now_local.date():
        return None

    grid = GRID_MINUTES
    minutes = now_local.hour * 60 + now_local.minute
    has_leftover = now_local.second or now_local.microsecond
    remainder = minutes % grid
    if remainder or has_leftover:
        rounded = minutes + (grid - remainder if remainder else grid)
    else:
        rounded = minutes

    # Rounding crossed midnight, or the clock is already at/past the window end
    # → no forward slot can exist today. The two operands use different bases on
    # purpose: `rounded >= 24*60` guards the post-rounding midnight wrap (so we
    # never build an out-of-range time), while `minutes >= window.end_minutes`
    # uses the pre-rounding clock so a time already at/after the window end
    # short-circuits regardless of grid rounding. Both funnel to the day_end
    # no-fit sentinel — do not "simplify" them to a single base.
    if rounded >= 24 * 60 or minutes >= window.end_minutes:
        return window.day_end
    if rounded < window.start_minutes:
        return window.day_start
    hour, minute = divmod(rounded, 60)
    return datetime.time(hour, minute)


def _validation_error_detail(e: ValidationError) -> dict:
    """Return the richest available detail from a ``ValidationError``.

    ``message_dict`` only exists when the error was constructed with
    per-field data (typically via ``full_clean``). A bare
    ``ValidationError("msg")`` has no ``message_dict`` and accessing it
    would raise ``AttributeError``. Fall back to ``str(e)`` so a future
    model-validator refactor can't produce a cryptic 500.
    """
    return getattr(e, "message_dict", None) or {"detail": str(e)}



def _persist_mutation_diff(
    schedule: Schedule, locked_blocks: list[TimeBlock], diff: MutationDiff
) -> None:
    """Persist a validated diff and map row failures to the source action."""
    try:
        persist_command_diff(schedule, locked_blocks, diff)
    except PersistenceError as error:
        if not isinstance(error.cause, ValidationError):
            raise error.cause from error
        raise _Rollback(
            _action_error(error.action_index or 0, _validation_error_detail(error.cause))
        ) from error


def _ai_context_fingerprint(schedule, blocks, rules, schedule_settings, categories, template=None):
    """Include every mutable prompt policy in the stale-intent guard."""
    payload = {
        "schedule": compute_apply_context_fingerprint(
            schedule=schedule, blocks=blocks, rules=rules
        ),
        "window": [schedule_settings.window.start_str, schedule_settings.window.end_str],
        "time_zone": schedule_settings.time_zone,
        "categories": [serialize_category(category) for category in categories],
    }
    if template is not None:
        payload["template"] = {
            "id": template.id,
            "name": template.name,
            "type": template.type,
            "blocks": template.blocks,
        }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _load_ai_context_sync(user, parsed_date, expected_revision, *, draft=False):
    """Capture one prompt context while policy and schedule writers are excluded."""

    def capture(locked_user):
        schedule, _ = Schedule.objects.get_or_create(user=locked_user, date=parsed_date)
        if schedule.revision != expected_revision:
            raise ScheduleChanged()
        blocks = list(schedule.time_blocks.order_by("start_time", "sort_order", "id"))
        rules = list(Rule.objects.filter(user=user, is_active=True).order_by("-priority", "id"))
        schedule_settings = get_schedule_settings(user)
        categories = ordered_categories(user)
        template = (
            Template.objects.filter(
                user=user, type=Template.slot_type_for_date(parsed_date)
            ).first()
            if draft
            else None
        )
        fingerprint = _ai_context_fingerprint(
            schedule, blocks, rules, schedule_settings, categories, template
        )
        schedule._schedule_window = schedule_settings.window
        schedule._categories = categories
        return schedule, blocks, rules, schedule_settings, template, fingerprint

    return run_user_maintenance(user.pk, capture)


def _apply_actions_sync(
    schedule: Schedule,
    result: AIChatResult,
    *,
    expected_revision: int,
    expected_fingerprint: str,
    interaction_id: int | None = None,
):
    """Validate intent and persist a plan through the shared day executor."""

    def mutate(ctx):
        locked_schedule, locked_blocks = ctx.schedule, ctx.blocks
        locked_rules = list(
            Rule.objects.filter(user_id=schedule.user_id, is_active=True)
            .only("id", "text", "priority")
            .order_by("-priority", "id")
        )
        categories = ordered_categories(locked_schedule.user)
        schedule_settings = get_schedule_settings(locked_schedule.user)
        fingerprint = _ai_context_fingerprint(
            locked_schedule, locked_blocks, locked_rules, schedule_settings, categories
        )
        if fingerprint != expected_fingerprint:
            logger.warning(
                "schedule_changed during AI apply (user=%s, schedule=%s, interaction=%s)",
                schedule.user_id,
                schedule.id,
                interaction_id,
            )
            raise ScheduleChanged()
        allowed_categories = {category.slug for category in categories}
        for index, action in enumerate(result.parsed_actions):
            category = (
                action["changes"].get("category")
                if action.get("type") == "update"
                else action.get("category")
            )
            if isinstance(category, str) and category not in allowed_categories:
                return _action_error(index, "invalid category")
        window = schedule_settings.window
        now_local = timezone.localtime(
            timezone.now(), resolve_time_zone(schedule_settings.time_zone)
        )
        plan_result = plan_mutations(
            snapshot_from_blocks(locked_schedule, locked_blocks),
            result.parsed_actions,
            day_start=window.start_str,
            day_end=window.end_str,
            earliest_start=_earliest_start(locked_schedule.date, window, now_local),
        )
        if isinstance(plan_result, PlanError):
            return _action_error(plan_result.action_index, plan_result.detail)
        _persist_mutation_diff(locked_schedule, locked_blocks, plan_result.diff)
        if plan_result.diff.deletes or plan_result.diff.updates or plan_result.diff.creates:
            locked_schedule.mark_active_on_edit()
        return plan_result

    try:
        return execute_schedule_mutation(schedule.user_id, schedule.pk, expected_revision, mutate)
    except ScheduleChanged as exc:
        raise _Rollback(schedule_changed_response(exc)) from exc
    except MutationRejected as exc:
        raise _Rollback(exc.response) from exc


def _apply_draft_sync(
    schedule: Schedule, result: AIDraftResult, *, expected_revision: int, expected_fingerprint: str
):
    """Check revision, policy context and emptiness in the same write transaction."""

    def mutate(ctx):
        locked_schedule = ctx.schedule
        if ctx.blocks:
            return JsonResponse(
                {
                    "errors": {
                        "detail": "Schedule already has blocks; delete them before regenerating."
                    }
                },
                status=409,
            )
        categories = ordered_categories(locked_schedule.user)
        schedule_settings = get_schedule_settings(locked_schedule.user)
        rules = list(
            Rule.objects.filter(user_id=schedule.user_id, is_active=True).order_by(
                "-priority", "id"
            )
        )
        template = Template.objects.filter(
            user_id=schedule.user_id, type=Template.slot_type_for_date(schedule.date)
        ).first()
        fingerprint = _ai_context_fingerprint(
            locked_schedule, ctx.blocks, rules, schedule_settings, categories, template
        )
        if fingerprint != expected_fingerprint:
            logger.warning(
                "schedule_changed during AI draft apply (user=%s, schedule=%s)",
                schedule.user_id,
                schedule.id,
            )
            raise ScheduleChanged()
        allowed_categories = {category.slug for category in categories}
        commands = []
        for idx, action in enumerate(result.parsed_actions):
            if action["category"] not in allowed_categories:
                return _action_error(idx, "invalid category")
            commands.append(
                CreateCommand(
                    title=action["title"].strip(),
                    category=action["category"],
                    start_time=parse_time(action["start_time"]),
                    end_time=parse_time(action["end_time"]),
                    sort_order=idx,
                    action_index=idx,
                )
            )
        try:
            plan = plan_commands(
                snapshot_from_blocks(locked_schedule, ctx.blocks),
                commands,
                policy=DRAFT,
                window=schedule_settings.window,
            )
        except CommandError as error:
            return _action_error(error.action_index or 0, error.message)
        _persist_mutation_diff(locked_schedule, ctx.blocks, plan.diff)

    try:
        return execute_schedule_mutation(schedule.user_id, schedule.pk, expected_revision, mutate)
    except ScheduleChanged as exc:
        raise _Rollback(schedule_changed_response(exc)) from exc
    except MutationRejected as exc:
        raise _Rollback(exc.response) from exc


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

    data, err = parse_json_object(request, allow_empty=True, max_bytes=None)
    if err is not None:
        return err
    try:
        expected_revision = parse_expected_revision(data)
    except ScheduleChanged as exc:
        return schedule_changed_response(exc)
    user = await request.auser()
    try:
        (
            schedule,
            current_blocks,
            rules,
            schedule_settings,
            template,
            expected_fingerprint,
        ) = await sync_to_async(_load_ai_context_sync, thread_sensitive=True)(
            user, parsed_date, expected_revision, draft=True
        )
    except ScheduleChanged as exc:
        return schedule_changed_response(exc)

    if current_blocks:
        return JsonResponse(
            {
                "errors": {
                    "detail": ("Schedule already has blocks; delete them before regenerating.")
                }
            },
            status=409,
        )

    if template is None:
        return JsonResponse(
            {"errors": {"detail": ("No template configured for this day type. Open Settings.")}},
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
        return rate_limited_response()

    history_start = parsed_date - datetime.timedelta(days=settings.LLM_HISTORY_DAYS)
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
    try:
        now = timezone.localtime(timezone.now(), resolve_time_zone(schedule_settings.time_zone))
        result = await run_draft(schedule, template, history, rules, now)
    except AIError as e:
        raw = getattr(e, "raw_response_text", "") or str(e)
        await _log_interaction(schedule, "[DRAFT]", raw, [], kind=AIInteraction.Kind.DRAFT)
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
        if isinstance(e, AIParseError):
            # Feature 0084: the client gets the generic detail; the real
            # validation string (which can echo model-supplied text, e.g. an
            # unresolved category label) goes to the log at DEBUG only — the
            # draft audit row above already keeps ``raw`` (unchanged).
            logger.warning("AI draft parse failure (user=%s, schedule=%s)", user.id, schedule.id)
            logger.debug("AI draft parse failure detail: %s", e)
            detail = AI_PARSE_ERROR_DETAIL
        else:
            detail = str(e)
        return JsonResponse({"errors": {"detail": detail}}, status=status)

    interaction = await _log_interaction(
        schedule,
        "[DRAFT]",
        result.raw_response_text,
        result.parsed_actions,
        kind=AIInteraction.Kind.DRAFT,
    )

    try:
        applied_result = await sync_to_async(_apply_draft_sync, thread_sensitive=True)(
            schedule,
            result,
            expected_revision=expected_revision,
            expected_fingerprint=expected_fingerprint,
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
    logger.info(
        "AI draft applied (user=%s, schedule=%s, actions=%s)",
        user.id,
        schedule.id,
        len(result.parsed_actions),
    )
    return JsonResponse(
        {
            **applied_result.snapshot,
            "explanation": result.explanation,
        }
    )


# ---------------------------------------------------------------------------
# Chat (feature 0007): multi-turn AI conversation.
# ---------------------------------------------------------------------------


def _validate_chat_messages(messages: object) -> str | None:
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
        # Optional replay-guard wire markers (feature 0083): client-supplied
        # correctness/UX hints, not a security boundary — see
        # ``ai.replay_guard`` and RULES.md. Only valid on assistant turns.
        for flag_name in ("is_ask", "is_error"):
            if flag_name not in msg:
                continue
            if not isinstance(msg[flag_name], bool):
                return f"messages[{idx}].{flag_name} must be a boolean"
            if role != "assistant":
                return f"messages[{idx}].{flag_name} is only valid on assistant turns"
        if "applied_add_block_ids" in msg:
            ids = msg["applied_add_block_ids"]
            if role != "assistant":
                return f"messages[{idx}].applied_add_block_ids is only valid on assistant turns"
            if (
                not isinstance(ids, list)
                or len(ids) > MAX_ACTIONS_PER_COMMAND
                or any(type(block_id) is not int or block_id <= 0 for block_id in ids)
            ):
                return f"messages[{idx}].applied_add_block_ids must be a list of block IDs"
        content = msg.get("content")
        if not isinstance(content, str):
            return f"messages[{idx}].content must be a string"
        if not content.strip():
            return f"messages[{idx}].content cannot be blank"
        if len(content) > settings.LLM_MAX_COMMAND_CHARS:
            return f"messages[{idx}].content too long (max {settings.LLM_MAX_COMMAND_CHARS} chars)"
        total_chars += len(content)
        # Roles strictly alternate, starting with user.
        expected = "user" if idx % 2 == 0 else "assistant"
        if role != expected:
            return (
                f"messages[{idx}].role must be {expected!r} "
                f"(roles must strictly alternate user/assistant)"
            )

    if total_chars > settings.LLM_CHAT_MAX_TOTAL_CHARS:
        return f"total content too long ({total_chars} > {settings.LLM_CHAT_MAX_TOTAL_CHARS} chars)"

    if messages[-1]["role"] != "user":
        return "messages must end with a user turn"

    return None


def _transcript_sha256(messages: list[dict]) -> str:
    """Stable hash of the client-supplied transcript for audit rows.

    Uses ``sort_keys=True`` and ``ensure_ascii=False`` so the hash is
    invariant under JSON re-encoding but does NOT collapse unicode
    differently than the wire form (we want the hash to match what the
    client actually sent, which is ``ensure_ascii=False`` after our
    server's ``json.loads``).
    """
    payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_chat_audit_response(
    messages: list[dict],
    raw_or_str: str,
    error_class: str | None,
    *,
    unresolved_categories: list[dict] | None = None,
    error_detail: str | None = None,
) -> str:
    """Build the JSON-encoded ``ai_response`` payload for a chat audit row.

    Same shape for success and failure rows; ``error_class`` is ``None``
    for success and the exception class name for failure. Both rows
    carry the transcript hash so a future audit can group rows that
    belong to the same client-supplied transcript.

    ``unresolved_categories`` (feature 0084, issue #209) — a success-row-only
    list of ``{"original_index", "task_id", "dropped"}`` dicts for any
    ``update`` action whose category the server couldn't resolve to a slug.
    Keyed by ``original_index`` — the position in the MODEL's own ``actions``
    inside ``raw``, a separate index space from ``outcomes``' post-
    normalisation ``action_index`` (see ``ai/category_resolution.py``). The
    rejected value itself is never included here: it's the user's own
    wording, and ``raw`` already holds it.

    ``error_detail`` (feature 0084) — a failure-row-only ``AIParseError``
    message, present so the real validation detail survives even though the
    client-facing ``errors.detail`` becomes the generic
    ``AI_PARSE_ERROR_DETAIL``. Both optional fields, and ``error_class``, are
    inserted BEFORE ``raw`` so they survive the ``_MAX_AI_RESPONSE_LOG_LEN`` truncation that
    slices this JSON string from the front on a huge model response.
    """
    payload = {
        "transcript_sha256": _transcript_sha256(messages),
        "turn_count": len(messages),
    }
    if unresolved_categories:
        payload["unresolved_categories"] = unresolved_categories
    if error_detail is not None:
        payload["error_detail"] = error_detail
    if error_class is not None:
        payload["error_class"] = error_class
    payload["raw"] = raw_or_str
    return json.dumps(payload, ensure_ascii=False)


async def _log_chat_failure(
    schedule: Schedule, last_user_msg: str, messages: list[dict], exc: Exception
) -> None:
    """Persist the failure-row variant of the chat audit envelope."""
    raw = getattr(exc, "raw_response_text", "") or str(exc)
    # Feature 0084: only ``AIParseError`` carries a validation-detail message
    # worth keeping separately — other ``AIError`` subclasses already have
    # their (non-model-echoing) ``str(exc)`` as ``raw`` above.
    error_detail = str(exc)[:_MAX_ERROR_DETAIL_LEN] if isinstance(exc, AIParseError) else None
    payload = _build_chat_audit_response(
        messages, raw, error_class=type(exc).__name__, error_detail=error_detail
    )
    await _log_interaction(schedule, last_user_msg, payload, [], kind=AIInteraction.Kind.CHAT)


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
      5. Validate UUID/body hash; replay or reserve a durable identity.
      6. Capture revision/policies, then consume one rate-limit token.
      7. Release the context capture's database lock.
      8. ``run_chat`` outside any transaction.
      9. Audit-log this turn (success-row variant; failure-row was
         logged in the ``except AIError`` branch).
     10. Fence the lease, apply actions and store the terminal HTTP result
         together, including ask/no-op/error results. Audit is best effort.
    """
    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return JsonResponse({"errors": {"date": "Invalid date format."}}, status=400)

    data, err = parse_json_object(request, max_bytes=None)
    if err is not None:
        return err

    messages = data.get("messages")
    err = _validate_chat_messages(messages)
    if err is not None:
        return JsonResponse({"errors": {"messages": err}}, status=400)
    try:
        expected_revision = parse_expected_revision(data)
    except ScheduleChanged as exc:
        return schedule_changed_response(exc)
    try:
        identity, body_hash = request_identity(data)
    except ValueError as exc:
        return JsonResponse({"errors": {"request_id": str(exc)}}, status=400)
    user = await request.auser()
    claim = await sync_to_async(claim_request, thread_sensitive=True)(
        user.pk, parsed_date, identity, body_hash
    )
    if not isinstance(claim, ChatClaim):
        return claim

    async def terminal(response):
        return await sync_to_async(finish_request, thread_sensitive=True)(claim, lambda: response)
    try:
        (
            schedule,
            current_blocks,
            rules,
            schedule_settings,
            _,
            expected_fingerprint,
        ) = await sync_to_async(_load_ai_context_sync, thread_sensitive=True)(
            user, parsed_date, expected_revision
        )
    except ScheduleChanged as exc:
        return await terminal(schedule_changed_response(exc))

    if not await _consume_rate_limit(user.id, "ai_chat_rl", settings.LLM_CHAT_RATE_LIMIT_PER_HOUR):
        return await terminal(rate_limited_response())

    last_user_msg = messages[-1]["content"]

    try:
        now = timezone.localtime(timezone.now(), resolve_time_zone(schedule_settings.time_zone))
        result = await run_chat(messages, schedule, current_blocks, rules, now)
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
        # Feature 0084: the client gets a generic detail for a parse
        # failure — the real validation string (which can echo model-
        # supplied text) is kept only in the audit row's ``error_detail``
        # (see ``_log_chat_failure``), never sent to the client.
        detail = AI_PARSE_ERROR_DETAIL if isinstance(e, AIParseError) else str(e)
        return await terminal(JsonResponse({"errors": {"detail": detail}}, status=status))

    audit_response = _build_chat_audit_response(
        messages,
        result.raw_response_text,
        error_class=None,
        unresolved_categories=[
            {"original_index": r.original_index, "task_id": r.task_id, "dropped": r.dropped}
            for r in result.unresolved_categories
        ],
    )
    interaction = await _log_interaction(
        schedule,
        last_user_msg,
        audit_response,
        result.parsed_actions,
        kind=AIInteraction.Kind.CHAT,
    )

    response = await sync_to_async(finish_request, thread_sensitive=True)(
        claim,
        lambda: _finish_chat_sync(
            user, schedule, current_blocks, messages, result, interaction,
            expected_revision, expected_fingerprint,
        ),
    )
    if response.status_code == 200 and not getattr(response, "chat_request_replayed", False):
        outcomes = json.loads(response.content).get("outcomes")
        await _mark_success(interaction, outcomes or None)
    return response


def _finish_chat_sync(
    user, schedule, current_blocks, messages, result, interaction,
    expected_revision, expected_fingerprint,
):
    """Build the result under the durable operation's outer write transaction."""
    def unchanged_snapshot():
        confirmed = _apply_actions_sync(
            schedule,
            replace(result, parsed_actions=[]),
            expected_revision=expected_revision,
            expected_fingerprint=expected_fingerprint,
            interaction_id=interaction.id if interaction else None,
        )
        return confirmed.snapshot

    if result.ask is not None or not result.parsed_actions:
        try:
            snapshot = unchanged_snapshot()
        except _Rollback as rb:
            return rb.response

    # Clarifying-question turn — no mutations, no schedule status flip.
    if result.ask is not None:
        return JsonResponse(
            {
                **snapshot,
                "blocks": None,
                "explanation": result.explanation,
                "ask": result.ask,
                "applied": False,
                "partial": False,
                "outcomes": [],
            }
        )

    # Feature 0084 (issue #209): every parsed action was an ``update`` whose
    # ONLY change was a category the server couldn't resolve to a slug, so
    # ``normalize_action_categories`` dropped it — ``parsed_actions`` is
    # empty here but this is NOT chit-chat (unlike the branch below): the
    # model DID intend a mutation, it just needs the category clarified.
    # ``explanation`` is server-owned (``GUARD_EXPLANATION``, not the
    # model's) because the model's explanation could claim a category
    # change that never happened.
    if not result.parsed_actions and result.unresolved_categories:
        block_titles = {block.id: _safe_block_title(block) for block in current_blocks}
        return JsonResponse(
            {
                **snapshot,
                "blocks": None,
                "explanation": GUARD_EXPLANATION,
                "ask": _build_category_ask(
                    result.unresolved_categories, block_titles, schedule._categories
                ),
                "applied": False,
                "partial": False,
                "outcomes": [],
            }
        )

    # Chit-chat / "thanks" turn — empty actions and null ask.
    if not result.parsed_actions:
        return JsonResponse(
            {
                **snapshot,
                "blocks": None,
                "explanation": result.explanation,
                "ask": None,
                "applied": False,
                "partial": False,
                "outcomes": [],
            }
        )

    # The replay guard skips the whole turn when an add was copied from a
    # previous message. Its response still checks revision and prompt context
    # under the write lock before returning schedule metadata.
    offending = find_replayed_actions(
        result.parsed_actions,
        messages,
        existing_blocks={block.id: block.title for block in current_blocks},
    )
    if offending:
        try:
            snapshot = unchanged_snapshot()
        except _Rollback as rb:
            return rb.response
        return _replay_guard_response(
            interaction,
            result.parsed_actions,
            offending,
            user_id=user.id,
            schedule_id=schedule.id,
            snapshot=snapshot,
        )

    # A relative add must not fall through to ordinary automatic placement.
    # The provider can omit times from "add Vocal after Gym", which would
    # otherwise put Vocal in the first free slot, possibly before Gym.
    relative_ask = relative_add_guard_ask(messages, result.parsed_actions, current_blocks)
    if relative_ask is not None:
        try:
            snapshot = unchanged_snapshot()
        except _Rollback as rb:
            return rb.response
        return JsonResponse(
            {
                **snapshot,
                "blocks": None,
                "explanation": GUARD_EXPLANATION,
                "ask": relative_ask,
                "applied": False,
                "partial": False,
                "outcomes": [],
            }
        )

    # The apply path re-fetches under the write lock and validates the final
    # candidate schedule before persisting its accepted diff.
    try:
        applied_result = _apply_actions_sync(
            schedule,
            result,
            expected_fingerprint=expected_fingerprint,
            expected_revision=expected_revision,
            interaction_id=interaction.id if interaction else None,
        )
    except _Rollback as rb:
        logger.warning(
            "AI chat apply failed (user=%s, schedule=%s, actions=%s)",
            user.id,
            schedule.id,
            len(result.parsed_actions),
        )
        return rb.response

    plan = applied_result.value
    outcome_payload = [action_outcome_to_dict(outcome) for outcome in plan.outcomes]

    protected_ids = {
        block.id for block in current_blocks if block.origin != TimeBlock.Origin.MANUAL
    }
    block_titles = {
        block["id"]: "[private block]" if block["id"] in protected_ids else block["title"]
        for block in applied_result.snapshot["blocks"]
    }
    create_titles = {
        index: action.get("title", "New block")
        for index, action in enumerate(result.parsed_actions)
        if action.get("type") == "add"
    }
    # Feature 0084 (issue #209): the time-conflict resolution ask wins when
    # both are pending — the user can answer only one question per turn, and
    # a skipped time work item needs a concrete slot before anything else
    # about that action matters. The category ask covers the issue's own
    # repro (an update whose unresolved category was stripped while its time
    # change applies here, ``applied: true``) and a sibling category-only
    # update that was dropped outright.
    ask = _build_resolution_ask(plan.outcomes, block_titles, create_titles) or _build_category_ask(
        result.unresolved_categories, block_titles, schedule._categories
    )
    applied = bool(plan.diff.deletes or plan.diff.updates or plan.diff.creates)
    logger.info(
        "AI chat applied (user=%s, schedule=%s, actions=%s)",
        user.id,
        schedule.id,
        len(result.parsed_actions),
    )
    return JsonResponse(
        {
            **applied_result.snapshot,
            "explanation": result.explanation,
            "ask": ask,
            "applied": applied,
            "partial": plan.overall_status == "partial",
            "outcomes": outcome_payload,
        }
    )
