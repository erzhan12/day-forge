"""Analytics endpoints: per-day review panel + Mark-reviewed + notes.

Three views:

* ``analytics_view`` — Inertia-rendered ``GET /analytics/<date>/``.
  Recomputes-on-visit while the schedule is ``active``; serves the
  frozen snapshot for ``reviewed``.
* ``mark_reviewed`` — ``POST /api/analytics/schedules/<date>/mark-reviewed/``.
  Hard-idempotent on ``REVIEWED`` (a retry returns the persisted
  snapshot regardless of payload). The two load-bearing ordering rules:
    1. Body is NOT parsed until after the under-lock status re-check.
       A retry with a malformed payload to a reviewed schedule still
       gets the snapshot, not a 400.
    2. ``select_for_update`` on the parent ``Schedule`` row + a
       double-checked status under the lock. Closes both the
       PATCH-vs-mark_reviewed race and the mark_reviewed-vs-mark_reviewed
       race. Pattern mirrors ``ai_generate_draft`` — see RULES.md
       "Locking an empty child queryset locks nothing".
* ``update_review_notes`` — ``PATCH /api/analytics/reviews/<pk>/notes/``.
  Notes are the only field editable post-review.
"""
import datetime
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from inertia import render as inertia_render
from schedules.http import reject_oversized_body
from schedules.models import Schedule, TimeBlock

from analytics.models import DailyReview
from analytics.services import compute_streak, recompute_review_from_schedule

logger = logging.getLogger(__name__)

NOTES_MAX_CHARS = 2000


def _block_to_dict(block: TimeBlock) -> dict:
    """Match ``schedules.http.block_to_dict``. Duplicated locally rather
    than imported because the analytics view forwards blocks through
    Inertia and shouldn't depend on the schedules HTTP shim's churn."""
    return {
        "id": block.id,
        "title": block.title,
        "start_time": block.start_time.strftime("%H:%M"),
        "end_time": block.end_time.strftime("%H:%M"),
        "category": block.category,
        "is_completed": block.is_completed,
        "sort_order": block.sort_order,
    }


def _review_to_dict(review: DailyReview) -> dict:
    """Serialise a ``DailyReview`` to the shape consumed by
    ``frontend/src/types/index.ts:DailyReview``."""
    return {
        "id": review.id,
        "schedule_id": review.schedule_id,
        "date": review.schedule.date.isoformat(),
        "status": review.schedule.status,
        "planned_count": review.planned_count,
        "completed_count": review.completed_count,
        "skipped_count": review.skipped_count,
        "completion_rate": review.completion_rate,
        "planned_minutes_by_category": review.planned_minutes_by_category,
        "completed_minutes_by_category": review.completed_minutes_by_category,
        "notes": review.notes,
        "created_at": review.created_at.isoformat(),
        "updated_at": review.updated_at.isoformat(),
    }


def _streak_payload(user) -> dict:
    return {
        "current": compute_streak(user),
        "threshold": settings.ANALYTICS_STREAK_THRESHOLD,
        "window_days": settings.ANALYTICS_STREAK_WINDOW_DAYS,
    }


def _parse_date(date: str):
    """Returns (parsed_date, error_response) — error is non-None on bad
    input (matches the convention from every other JSON view)."""
    try:
        return datetime.date.fromisoformat(date), None
    except ValueError:
        return None, JsonResponse(
            {"errors": {"date": "Invalid date format."}}, status=400
        )


@login_required
@require_http_methods(["GET"])
def analytics_view(request, date):
    """Inertia render of the per-day analytics panel.

    400 on future dates (analytics is past-/today-only). 404 when no
    Schedule row exists — analytics is read-only on past data and
    shouldn't auto-create.

    Recompute strategy:
      - ``status == reviewed`` → serve the persisted snapshot frozen.
        Back-compat: a ``reviewed`` schedule predating Phase 6 may have
        no row; recompute once and persist in that case so the user
        still sees something.
      - otherwise → recompute on every visit. ``updated_at`` advances
        each time, which is how the test suite pins "freshness while
        active vs. frozen after review".
    """
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return HttpResponseBadRequest("Invalid date format. Use YYYY-MM-DD.")

    # Use ``timezone.localdate()`` to match ``compute_review_stats`` /
    # ``compute_streak`` — both go through ``timezone.localtime()``. With
    # ``TIME_ZONE = "UTC"`` and a host in another zone, ``date.today()``
    # would disagree around midnight, letting through dates the stats
    # layer treats as future (or vice versa).
    today = timezone.localdate()
    if parsed_date > today:
        return HttpResponseBadRequest("Analytics is past-only.")

    schedule = (
        Schedule.objects.filter(user=request.user, date=parsed_date)
        .prefetch_related("time_blocks")
        .first()
    )
    if schedule is None:
        raise Http404("No schedule for this date.")

    if schedule.status == Schedule.Status.REVIEWED:
        review = DailyReview.objects.filter(schedule=schedule).first()
        if review is None:
            # Back-compat one-shot recompute for pre-Phase-6 reviewed rows.
            review = recompute_review_from_schedule(schedule)
    else:
        review = recompute_review_from_schedule(schedule)

    # Cache the in-scope ``schedule`` on the review instance so
    # ``_review_to_dict`` doesn't issue an extra SELECT for the parent
    # row when it reads ``review.schedule.date`` / ``.status``. Both
    # the back-compat lookup and the recompute path return a review
    # whose ``schedule`` FK is not pre-fetched.
    review.schedule = schedule

    blocks = list(
        schedule.time_blocks.all().order_by("start_time", "sort_order")
    )
    return inertia_render(
        request,
        "Analytics",
        {
            "review": _review_to_dict(review),
            "streak": _streak_payload(request.user),
            "schedule": {
                "id": schedule.id,
                "date": schedule.date.isoformat(),
                "status": schedule.status,
            },
            "blocks": [_block_to_dict(b) for b in blocks],
            "date": parsed_date.isoformat(),
        },
    )


def _validate_notes(value, *, required: bool):
    """Return ``(notes_str, error_response)``. ``required=True`` rejects a
    missing field (PATCH semantics); ``required=False`` returns ``(None,
    None)`` when the field is absent (mark_reviewed semantics — notes
    are optional on the active→reviewed flip)."""
    if value is None:
        if required:
            return None, JsonResponse(
                {"errors": {"notes": "notes is required."}}, status=400
            )
        return None, None
    if not isinstance(value, str):
        return None, JsonResponse(
            {"errors": {"notes": "notes must be a string."}}, status=400
        )
    if len(value) > NOTES_MAX_CHARS:
        return None, JsonResponse(
            {
                "errors": {
                    "notes": f"notes must be ≤ {NOTES_MAX_CHARS} characters."
                }
            },
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

    schedule = Schedule.objects.filter(
        user=request.user, date=parsed_date
    ).first()
    if schedule is None:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)

    # Pre-lock fast paths. Cheap early-out, NOT load-bearing for
    # correctness — the under-lock recheck below is what closes the race.
    if schedule.status == Schedule.Status.DRAFT:
        return JsonResponse(
            {
                "errors": {
                    "detail": (
                        "Cannot review a draft schedule — make at least one "
                        "edit first."
                    )
                }
            },
            status=400,
        )
    if schedule.status == Schedule.Status.REVIEWED:
        # Hard idempotency: do NOT parse the body, do NOT acquire the
        # lock, do NOT recompute. A retry with a stale or corrupted
        # payload still returns the persisted snapshot.
        review = DailyReview.objects.filter(schedule=schedule).first()
        if review is None:
            # Back-compat one-shot recompute for pre-Phase-6 reviewed
            # rows that have no DailyReview yet.
            review = recompute_review_from_schedule(schedule)
        review.schedule = schedule  # avoid an extra SELECT in serialiser
        return JsonResponse(_review_to_dict(review))

    with transaction.atomic():
        # Lock the parent ``Schedule`` row. Locking the (potentially
        # empty) child TimeBlock queryset would acquire zero locks under
        # PostgreSQL — see RULES.md "Locking an empty child queryset
        # locks nothing". This serialises every potential writer for
        # this schedule (block_detail, mark_reviewed, ai_command, etc.)
        # behind one queue.
        locked = (
            Schedule.objects.select_for_update()
            .prefetch_related("time_blocks")
            .get(pk=schedule.pk)
        )

        # Re-check status under the lock. Closes the
        # mark_reviewed-vs-mark_reviewed TOCTOU race: two concurrent
        # callers can both observe ACTIVE in the pre-lock check, both
        # enter the atomic block, both queue on the row lock; the second
        # would otherwise overwrite the first's freshly-frozen snapshot.
        if locked.status == Schedule.Status.REVIEWED:
            review = DailyReview.objects.filter(schedule=locked).first()
            if review is None:
                review = recompute_review_from_schedule(locked)
            review.schedule = locked  # avoid extra SELECT in serialiser
            return JsonResponse(_review_to_dict(review))
        if locked.status == Schedule.Status.DRAFT:
            return JsonResponse(
                {
                    "errors": {
                        "detail": (
                            "Cannot review a draft schedule — make at least "
                            "one edit first."
                        )
                    }
                },
                status=400,
            )

        # Only reachable when status == ACTIVE under the lock. Body
        # parsing is intentionally deferred to here so the REVIEWED
        # idempotent paths above never see a 400 from a malformed payload.
        if request.body == b"":
            data: dict = {}
        else:
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse(
                    {"errors": {"body": "Invalid JSON."}}, status=400
                )
            if not isinstance(data, dict):
                return JsonResponse(
                    {"errors": {"body": "Request body must be a JSON object."}},
                    status=400,
                )

        notes_value, notes_err = _validate_notes(
            data.get("notes"), required=False
        )
        if notes_err is not None:
            return notes_err

        review = recompute_review_from_schedule(locked)
        if notes_value is not None:
            review.notes = notes_value
            review.save(update_fields=["notes"])
        locked.mark_reviewed_if_active()
        # Refresh the in-memory ``review.schedule`` so the serialised
        # status reflects the just-flipped value.
        review.schedule = locked

    logger.info(
        "mark_reviewed: user=%s schedule=%s notes=%s",
        request.user.id,
        locked.id,
        "yes" if notes_value else "no",
    )
    return JsonResponse(_review_to_dict(review))


@login_required
@require_http_methods(["PATCH"])
def update_review_notes(request, pk):
    """Edit ``notes`` on an existing review row. Cross-user 404 (not 403)
    matches the project-wide convention from ``block_detail`` and
    ``template_detail``."""
    oversized = reject_oversized_body(request)
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

    notes_value, notes_err = _validate_notes(data.get("notes"), required=True)
    if notes_err is not None:
        return notes_err

    review = (
        DailyReview.objects.filter(pk=pk, schedule__user=request.user)
        .select_related("schedule")
        .first()
    )
    if review is None:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)

    review.notes = notes_value
    review.save(update_fields=["notes"])
    return JsonResponse(_review_to_dict(review))
