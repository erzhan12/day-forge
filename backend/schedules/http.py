"""Shared HTTP / validation helpers for the schedules domain.

Owned here (rather than inside ``schedules/api.py``) so sibling apps like
``ai/views.py`` can import public names without reaching into another
module's underscore-prefixed internals. ``schedules/api.py`` re-exports
these for its own call sites and keeps private aliases to avoid touching
every existing reference.

Keep this module import-light: only ``schedules.models`` and
``schedules.validators``. Anything from ``schedules.api`` would introduce
a circular import.
"""
import datetime

from django.core.exceptions import ValidationError
from django.http import JsonResponse

from schedules.models import TimeBlock
from schedules.validators import validate_five_minute_granularity

VALID_CATEGORIES = {c.value for c in TimeBlock.Category}
MAX_SORT_ORDER = 10_000
# Tight body-size cap for batch endpoints. Django already enforces
# ``DATA_UPLOAD_MAX_MEMORY_SIZE`` (2.5 MB default) in middleware, but a
# legitimate payload here is well under 20 KB. 100 KB is 5× headroom and
# avoids parsing several megabytes only to reject it further down. Returns
# HTTP 413 when exceeded.
MAX_REQUEST_BODY_BYTES = 100_000


def reject_oversized_body(request):
    """Return a 413 ``JsonResponse`` if ``request.body`` exceeds the cap,
    otherwise ``None``. Call before ``json.loads`` in batch endpoints.

    This is **not** the memory-safety gate for very large payloads — Django
    already enforces ``DATA_UPLOAD_MAX_MEMORY_SIZE`` (2.5 MB default) in
    middleware and raises ``RequestDataTooBig`` before any view runs, so
    bodies above that limit never reach us. What this check adds is:

    * a much tighter endpoint-specific cap (100 KB vs 2.5 MB), which
      avoids burning CPU to parse several megabytes of valid JSON only
      to reject it via the per-entry count/field checks below;
    * a structured 413 response with an explicit "Request body too
      large." error message, instead of Django's default 400.
    """
    if len(request.body) > MAX_REQUEST_BODY_BYTES:
        return JsonResponse(
            {"errors": {"body": "Request body too large."}},
            status=413,
        )
    return None


def is_plain_int(value) -> bool:
    """True if ``value`` is an ``int`` that isn't a ``bool``.

    Python's ``bool`` subclasses ``int``, so a bare ``isinstance(value,
    int)`` check accepts ``True``/``False``. Centralising the guard keeps
    the rationale in one place.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def parse_time(value):
    """Parse 'HH:MM' string to ``datetime.time``."""
    return datetime.datetime.strptime(value, "%H:%M").time()


def parse_time_or_error(field_name, value, block_id=None):
    """Parse an HH:MM string. Return ``(time, None)`` on success or
    ``(None, JsonResponse)`` with a 400 error on failure.

    ``block_id`` is appended to the error message when supplied so callers
    handling lists of entries can disambiguate which one was malformed.
    """
    suffix = f" for block {block_id}" if block_id is not None else ""
    try:
        return parse_time(value), None
    except (ValueError, TypeError):
        return None, JsonResponse(
            {"errors": {field_name: f"Invalid time format{suffix}. Use HH:MM."}},
            status=400,
        )


def validate_five_minute_or_error(*times):
    """Run ``validate_five_minute_granularity`` on every value. Return
    ``None`` on success or a 400 ``JsonResponse`` on the first failure."""
    try:
        for t in times:
            validate_five_minute_granularity(t)
    except ValidationError as e:
        return JsonResponse({"errors": {"time": str(e.message)}}, status=400)
    return None


def validate_time_range(start, end, block_id=None):
    """Verify ``start < end``. Return ``None`` on success or a 400
    ``JsonResponse`` otherwise."""
    if start >= end:
        suffix = f" for block {block_id}" if block_id is not None else ""
        return JsonResponse(
            {"errors": {"time": f"Start time must be before end time{suffix}."}},
            status=400,
        )
    return None


def validate_block_times(start_str, end_str, block_id=None, *, enforce_granularity=True):
    """Parse and validate a pair of HH:MM strings: format, 5-minute
    granularity, and ``start < end``.

    ``enforce_granularity=False`` skips only the 5-minute check — used by
    ``restore_blocks``, which re-persists previously-valid states that may
    legitimately be off-grid (from-event blocks, feature 0026). Format and
    range checks always run.

    Returns ``(start, end, None)`` on success or
    ``(None, None, JsonResponse)`` on the first failure.
    """
    start, err = parse_time_or_error("start_time", start_str, block_id=block_id)
    if err is not None:
        return None, None, err
    end, err = parse_time_or_error("end_time", end_str, block_id=block_id)
    if err is not None:
        return None, None, err
    if enforce_granularity:
        err = validate_five_minute_or_error(start, end)
        if err is not None:
            return None, None, err
    err = validate_time_range(start, end, block_id=block_id)
    if err is not None:
        return None, None, err
    return start, end, None


def validate_sort_order(value, block_id=None):
    """Verify ``value`` is an integer in ``[0, MAX_SORT_ORDER]``. Return
    ``None`` on success or a 400 ``JsonResponse`` otherwise.
    """
    suffix = f" for block {block_id}" if block_id is not None else ""
    if not is_plain_int(value):
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


def block_to_dict(block):
    return {
        "id": block.id,
        "title": block.title,
        "start_time": block.start_time.strftime("%H:%M"),
        "end_time": block.end_time.strftime("%H:%M"),
        "category": block.category,
        "is_completed": block.is_completed,
        "sort_order": block.sort_order,
    }


def times_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Pairwise overlap predicate for half-open intervals ``[start, end)``.

    Two blocks overlap iff ``a.start < b.end`` and ``a.end > b.start``.
    """
    return a_start < b_end and a_end > b_start
