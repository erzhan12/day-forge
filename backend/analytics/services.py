"""Analytics service layer.

Pure-ish functions that compute / persist daily review snapshots and
walk the streak window. Kept out of ``views.py`` so they're DB-only and
unit-testable without the HTTP layer; kept off ``models.py`` so we don't
get a ``models → services → models`` circular import.

Public surface:

* ``compute_review_stats(schedule, *, now=None) -> dict`` — pure
  aggregator over a single schedule's blocks. Returns the writable
  ``DailyReview`` field set; safe to call without DB writes.
* ``recompute_review_from_schedule(schedule, *, now=None) -> DailyReview``
  — ``update_or_create`` wrapper that preserves ``notes`` across
  recomputes.
* ``compute_streak(user, *, today=None) -> int`` — calendar-walk
  backward from yesterday. Gap day = break, zero-block schedule = skip.
"""
import datetime

from django.conf import settings
from django.utils import timezone
from schedules.models import Schedule, TimeBlock

from analytics.models import DailyReview


def _duration_minutes(start: datetime.time, end: datetime.time) -> int:
    """``end - start`` in minutes. Both are naive ``datetime.time`` so we
    promote to a fixed datetime before subtracting."""
    base = datetime.date.min
    delta = (
        datetime.datetime.combine(base, end)
        - datetime.datetime.combine(base, start)
    )
    return int(delta.total_seconds() // 60)


def compute_review_stats(schedule: Schedule, *, now=None) -> dict:
    """Aggregate one schedule's block list into ``DailyReview`` writable
    fields.

    ``now`` is an optional ``datetime`` injected for deterministic tests;
    when omitted, ``timezone.localtime()`` is read inside the call (NOT
    at module import) so a freezegun-style override on the caller side
    works.

    Today-aware "skipped" rule:
      - past day → every uncompleted block is skipped
      - today → only blocks with ``end_time < now.time()`` are skipped
        (still-future blocks aren't decided yet)
      - future day → never skipped (analytics_view rejects future dates
        anyway, but the function defends in depth)

    Returns a dict matching the writable ``DailyReview`` columns:
    ``planned_count``, ``completed_count``, ``skipped_count``,
    ``planned_minutes_by_category``, ``completed_minutes_by_category``.
    """
    if now is None:
        now = timezone.localtime()
    today = now.date() if isinstance(now, datetime.datetime) else now

    planned_count = 0
    completed_count = 0
    skipped_count = 0
    # Initialise both maps with every category at zero so the JSON shape
    # is stable for the frontend (no missing keys).
    planned_by_cat: dict[str, int] = {c.value: 0 for c in TimeBlock.Category}
    completed_by_cat: dict[str, int] = {c.value: 0 for c in TimeBlock.Category}

    for block in schedule.time_blocks.all():
        duration = _duration_minutes(block.start_time, block.end_time)
        planned_count += 1
        planned_by_cat[block.category] += duration

        if block.is_completed:
            completed_count += 1
            completed_by_cat[block.category] += duration
            continue

        # Uncompleted — apply the today-aware skip rule.
        if schedule.date < today:
            skipped_count += 1
        elif schedule.date == today:
            # Compare the block's end-of-window to "now" only when ``now``
            # is a datetime (the production path); a date-only ``now``
            # trivially can't decide partial-day skips and is treated as
            # "the day isn't over yet".
            if isinstance(now, datetime.datetime) and block.end_time < now.time():
                skipped_count += 1
        # future date → never skipped

    return {
        "planned_count": planned_count,
        "completed_count": completed_count,
        "skipped_count": skipped_count,
        "planned_minutes_by_category": planned_by_cat,
        "completed_minutes_by_category": completed_by_cat,
    }


def recompute_review_from_schedule(
    schedule: Schedule, *, now=None
) -> DailyReview:
    """Refresh (or create) the ``DailyReview`` row from current blocks.

    ``notes`` is intentionally NOT in ``defaults`` so a recompute
    preserves any user-entered notes from a prior review. ``updated_at``
    advances on every call (``auto_now``) so the view layer can pin
    "frozen-vs-fresh" idempotency in tests.
    """
    stats = compute_review_stats(schedule, now=now)
    review, _ = DailyReview.objects.update_or_create(
        schedule=schedule, defaults=stats
    )
    return review


def compute_streak(user, *, today=None) -> int:
    """Walk calendar dates backward from yesterday and count consecutive
    days at or above ``ANALYTICS_STREAK_THRESHOLD``.

    Semantics:
      - **Gap day** (no Schedule row at all) → hard break (the user
        didn't plan that day, so the streak ends).
      - **Zero-block schedule** → skip (rest day; doesn't count, doesn't
        break).
      - **Day with blocks** → use ``DailyReview.completion_rate`` if a
        row exists (cheap read), otherwise compute on the fly via
        ``compute_review_stats`` (no DB write — keeps the streak
        accurate for users who plan well but rarely open analytics).
      - ``rate is None`` (defensive: zero-planned that somehow has a
        review row) → skip rather than break.

    Capped at ``ANALYTICS_STREAK_WINDOW_DAYS`` to keep the query bounded
    on long-lived accounts.

    Query strategy: one SELECT for the entire window with
    ``select_related("daily_review")`` + ``prefetch_related("time_blocks")``,
    then walk in memory. The naive per-day loop issued up to N SELECTs
    (default 30) on every analytics page visit; users with long streaks
    paid for all of them every time. The bulk query is constant cost
    regardless of streak length.
    """
    if today is None:
        today = timezone.localdate()

    threshold = settings.ANALYTICS_STREAK_THRESHOLD
    window = settings.ANALYTICS_STREAK_WINDOW_DAYS

    window_start = today - datetime.timedelta(days=window)
    schedules = (
        Schedule.objects.filter(
            user=user, date__gte=window_start, date__lt=today
        )
        .select_related("daily_review")
        .prefetch_related("time_blocks")
    )
    by_date = {s.date: s for s in schedules}

    streak = 0
    for offset in range(1, window + 1):
        target_date = today - datetime.timedelta(days=offset)
        schedule = by_date.get(target_date)
        if schedule is None:
            break  # gap day — user didn't plan that day, streak ends

        blocks = list(schedule.time_blocks.all())
        if not blocks:
            continue  # zero-block "rest day" — skip without breaking

        review = getattr(schedule, "daily_review", None)
        if review is not None:
            rate = review.completion_rate
        else:
            stats = compute_review_stats(schedule)
            rate = (
                stats["completed_count"] / stats["planned_count"]
                if stats["planned_count"]
                else None
            )

        if rate is None:
            continue  # defensive — treat as rest day

        if rate >= threshold:
            streak += 1
            continue

        break  # below threshold — streak ends

    return streak
