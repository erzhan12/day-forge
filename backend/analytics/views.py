"""Per-day analytics, frozen review snapshots, and editable review notes.

Review writes use the shared User → Schedule → TimeBlock lock order. An
already-reviewed day returns its persisted review before parsing the request
or checking its revision, so retries remain stable even with malformed bodies.
"""

import datetime
import logging

from common.http import parse_json_object, reject_oversized_body
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from inertia import render as inertia_render
from schedules.categories import ordered_categories, serialize_category, sink_category
from schedules.models import Schedule, TimeBlock
from schedules.mutations import (
    MutationRejected,
    ScheduleChanged,
    execute_schedule_mutation,
    parse_expected_revision,
    run_user_maintenance,
    schedule_changed_response,
)
from schedules.serialization import serialize_block
from schedules.window import get_schedule_settings, resolve_time_zone, user_local_now
from templates_mgr.preferences import (
    get_user_preferences,
    ui_preferences_payload,
)

from analytics.models import DailyReview
from analytics.services import (
    compute_review_stats,
    compute_streak,
    freeze_review_snapshot,
    is_review_snapshot_current,
)

logger = logging.getLogger(__name__)

NOTES_MAX_CHARS = 2000


def _review_to_dict(
    schedule: Schedule, review: DailyReview | None, *, stats: dict | None = None
) -> dict:
    """Serialise a ``DailyReview`` to the shape consumed by
    ``frontend/src/types/index.ts:DailyReview``."""
    frozen = stats is None and is_review_snapshot_current(schedule, review)
    aggregates = stats if stats is not None else {
        "planned_count": review.planned_count,
        "completed_count": review.completed_count,
        "skipped_count": review.skipped_count,
        "planned_minutes_by_category": review.planned_minutes_by_category,
        "completed_minutes_by_category": review.completed_minutes_by_category,
    }
    planned = aggregates["planned_count"]
    return {
        "id": review.id if review else None,
        "schedule_id": schedule.id,
        "date": schedule.date.isoformat(),
        "status": schedule.status,
        **aggregates,
        "completion_rate": aggregates["completed_count"] / planned if planned else None,
        "notes": review.notes if review else "",
        "created_at": review.created_at.isoformat() if review else None,
        "updated_at": review.updated_at.isoformat() if review else None,
        "snapshot_kind": "frozen" if frozen else "current",
        "reviewed_revision": review.reviewed_revision if review else None,
    }


def _normalized_category_minutes(values, categories):
    """Fold stale persisted keys into the current sink without mutating history."""
    allowed = {category.slug for category in categories}
    sink = sink_category(categories).slug
    result = {category.slug: 0 for category in categories}
    for slug, minutes in (values or {}).items():
        numeric = (
            minutes if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) else 0
        )
        result[slug if slug in allowed else sink] += numeric
    return result


def _streak_payload(user, *, today) -> dict:
    return {
        "current": compute_streak(user, today=today),
        "threshold": settings.ANALYTICS_STREAK_THRESHOLD,
        "window_days": settings.ANALYTICS_STREAK_WINDOW_DAYS,
    }


def _parse_date(date: str):
    """Returns (parsed_date, error_response) — error is non-None on bad
    input (matches the convention from every other JSON view)."""
    try:
        return datetime.date.fromisoformat(date), None
    except ValueError:
        return None, JsonResponse({"errors": {"date": "Invalid date format."}}, status=400)


@login_required
@require_http_methods(["GET"])
def analytics_view(request, date):
    """Inertia render of the per-day analytics panel.

    400 on future dates (analytics is past-/today-only). 404 when no
    Schedule row exists — analytics is read-only on past data and
    shouldn't auto-create.

    Current statistics are computed in memory. A reviewed snapshot is used
    only when its recorded revision matches the schedule's revision.
    """
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return HttpResponseBadRequest("Invalid date format. Use YYYY-MM-DD.")

    # Resolve the user's persisted settings ONCE and reuse the object for
    # the day-boundary math here AND the schedule_window prop below (one
    # SELECT). Deriving now/today from a single ``timezone.now()`` read
    # avoids two calls straddling local midnight; ``today`` feeds the
    # future-date gate and the stats layer below.
    # Inlined (not schedules.window.user_local_now) on purpose: the helper
    # would issue its own get_schedule_settings, and we already need the
    # settings object for schedule_window — do NOT "simplify" to the helper.
    def load_analytics():
        schedule_settings = get_schedule_settings(request.user)
        now_local = timezone.localtime(
            timezone.now(), resolve_time_zone(schedule_settings.time_zone)
        )
        today = now_local.date()
        if parsed_date > today:
            return HttpResponseBadRequest("Analytics is past-only.")

        schedule = (
            Schedule.objects.filter(user=request.user, date=parsed_date)
            .prefetch_related(
                Prefetch(
                    "time_blocks",
                    queryset=TimeBlock.objects.order_by("start_time", "sort_order", "id"),
                )
            )
            .first()
        )
        if schedule is None:
            raise Http404("No schedule for this date.")

        categories = ordered_categories(request.user)
        review = DailyReview.objects.filter(schedule=schedule).first()
        stats = None
        if not is_review_snapshot_current(schedule, review):
            stats = compute_review_stats(schedule, now=now_local, categories=categories)
        review_data = _review_to_dict(schedule, review, stats=stats)
        # Category deletion can leave historical keys. Fold them for display.
        review_data["planned_minutes_by_category"] = _normalized_category_minutes(
            review_data["planned_minutes_by_category"], categories
        )
        review_data["completed_minutes_by_category"] = _normalized_category_minutes(
            review_data["completed_minutes_by_category"], categories
        )

        blocks = list(schedule.time_blocks.all())
        return (
            schedule,
            review_data,
            now_local,
            categories,
            schedule_settings,
            [serialize_block(block) for block in blocks],
        )

    # First-use helpers may create default rows. Resolve them before the read
    # transaction, then capture the day and streak under the same User lock
    # taken by schedule writers. The lock is a SELECT; GET does not update User.
    get_schedule_settings(request.user)
    ordered_categories(request.user)
    get_user_preferences(request.user)
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        captured = load_analytics()
        if isinstance(captured, HttpResponseBadRequest):
            return captured
        schedule, review_data, now_local, categories, schedule_settings, blocks_data = captured
        streak_data = _streak_payload(request.user, today=now_local.date())
        prefs = get_user_preferences(request.user)
    # schedule_settings already resolved above; reused here for schedule_window prop.
    return inertia_render(
        request,
        "Analytics",
        {
            "review": review_data,
            "streak": streak_data,
            "schedule": {
                "id": schedule.id,
                "date": schedule.date.isoformat(),
                "status": schedule.status,
                "revision": schedule.revision,
            },
            "blocks": blocks_data,
            "categories": [serialize_category(category) for category in categories],
            "date": parsed_date.isoformat(),
            "ui_preferences": ui_preferences_payload(prefs),
            "schedule_window": {
                "start": schedule_settings.window.start_str,
                "end": schedule_settings.window.end_str,
                "time_zone": schedule_settings.time_zone,
            },
        },
        template_data={"initial_theme": prefs.theme},
    )


def _validate_notes(value, *, required: bool):
    """Return ``(notes_str, error_response)``. ``required=True`` rejects a
    missing field (PATCH semantics); ``required=False`` returns ``(None,
    None)`` when the field is absent (mark_reviewed semantics — notes
    are optional on the active→reviewed flip)."""
    if value is None:
        if required:
            return None, JsonResponse({"errors": {"notes": "notes is required."}}, status=400)
        return None, None
    if not isinstance(value, str):
        return None, JsonResponse({"errors": {"notes": "notes must be a string."}}, status=400)
    if len(value) > NOTES_MAX_CHARS:
        return None, JsonResponse(
            {"errors": {"notes": f"notes must be ≤ {NOTES_MAX_CHARS} characters."}},
            status=400,
        )
    return value, None


@login_required
@require_http_methods(["POST"])
def mark_reviewed(request, date):
    """Flip ``active → reviewed`` and freeze the snapshot.

    See module docstring for the two load-bearing ordering rules.
    """
    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    parsed_date, err = _parse_date(date)
    if err is not None:
        return err

    schedule = Schedule.objects.filter(user=request.user, date=parsed_date).first()
    if schedule is None:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)

    def precondition(ctx):
        # Stable retries are resolved under the same lock before body parsing
        # or revision validation, including malformed or obsolete payloads.
        if ctx.schedule.status == Schedule.Status.REVIEWED:
            review = DailyReview.objects.filter(schedule=ctx.schedule).first()
            if not is_review_snapshot_current(ctx.schedule, review):
                # Explicit retry repairs a missing or stale snapshot under the
                # User and Schedule lock. It preserves notes and does not edit
                # the schedule, so its revision remains unchanged.
                review = freeze_review_snapshot(
                    ctx.schedule,
                    revision=ctx.schedule.revision,
                    now=user_local_now(request.user),
                )
            return _review_to_dict(ctx.schedule, review)
        if ctx.schedule.status == Schedule.Status.DRAFT:
            return JsonResponse(
                {
                    "errors": {
                        "detail": "Cannot review a draft schedule — make at least one edit first."
                    }
                },
                status=400,
            )
        return None

    body = {}

    def expected_revision(ctx):
        data, error = parse_json_object(request, allow_empty=True, max_bytes=None)
        if error is not None:
            raise MutationRejected(error)
        body.clear()
        body.update(data)
        return parse_expected_revision(data)

    def mutate(ctx):
        notes_value, notes_err = _validate_notes(body.get("notes"), required=False)
        if notes_err is not None:
            return notes_err
        review = freeze_review_snapshot(
            ctx.schedule,
            revision=ctx.schedule.revision + 1,
            now=user_local_now(request.user),
        )
        if notes_value is not None:
            review.notes = notes_value
            review.save(update_fields=["notes"])
        ctx.schedule.mark_reviewed_if_active()
        # The executor advances the persisted revision after this callback.
        # Set the in-memory value for the immediate review payload.
        ctx.schedule.revision = review.reviewed_revision
        return _review_to_dict(ctx.schedule, review)

    try:
        result = execute_schedule_mutation(
            request.user.pk, schedule.pk, expected_revision, mutate, precondition=precondition
        )
    except ScheduleChanged as exc:
        return schedule_changed_response(exc)
    except MutationRejected as exc:
        return exc.response
    logger.info(
        "mark_reviewed: user=%s schedule=%s changed=%s",
        request.user.id,
        schedule.id,
        result.changed,
    )
    return JsonResponse({**result.value, **result.snapshot})


@login_required
@require_http_methods(["PATCH"])
def update_review_notes(request, pk):
    """Edit ``notes`` on an existing review row. Cross-user 404 (not 403)
    matches the project-wide convention from ``block_detail`` and
    ``template_detail``."""
    data, err = parse_json_object(request)
    if err is not None:
        return err

    notes_value, notes_err = _validate_notes(data.get("notes"), required=True)
    if notes_err is not None:
        return notes_err

    schedule_id = DailyReview.objects.filter(
        pk=pk, schedule__user=request.user
    ).values_list("schedule_id", flat=True).first()
    if schedule_id is None:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    return _write_notes(request.user.pk, schedule_id, notes_value, review_id=pk)


def _write_notes(user_id, schedule_id, notes, *, review_id=None):
    def write(_user):
        schedule = Schedule.objects.select_for_update().filter(
            pk=schedule_id, user_id=user_id
        ).first()
        if schedule is None:
            return None
        if review_id is not None:
            review = DailyReview.objects.filter(pk=review_id, schedule=schedule).first()
            if review is None:
                return None
        else:
            review, _ = DailyReview.objects.get_or_create(schedule=schedule)
        review.notes = notes
        review.save(update_fields=["notes", "updated_at"])
        stats = None
        if not is_review_snapshot_current(schedule, review):
            stats = compute_review_stats(schedule)
        return _review_to_dict(schedule, review, stats=stats)

    result = run_user_maintenance(user_id, write)
    if result is None:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    return JsonResponse(result)


@login_required
@require_http_methods(["PATCH"])
def update_schedule_notes(request, date):
    parsed_date, err = _parse_date(date)
    if err is not None:
        return err
    data, err = parse_json_object(request)
    if err is not None:
        return err
    notes, err = _validate_notes(data.get("notes"), required=True)
    if err is not None:
        return err
    schedule_id = Schedule.objects.filter(
        user=request.user, date=parsed_date
    ).values_list("id", flat=True).first()
    if schedule_id is None:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    return _write_notes(request.user.pk, schedule_id, notes)
