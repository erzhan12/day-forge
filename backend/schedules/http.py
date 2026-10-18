"""Shared HTTP and validation helpers for the schedules domain.

Schedule endpoints and sibling apps import these public helpers directly.
Keep this module independent of ``schedules.api`` to avoid circular imports.
"""

from common.http import parse_json_object
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Model
from django.http import JsonResponse

from schedules import time_validation

MAX_SORT_ORDER = 10_000


def is_plain_int(value) -> bool:
    """True if ``value`` is an ``int`` that isn't a ``bool``.

    Python's ``bool`` subclasses ``int``, so a bare ``isinstance(value,
    int)`` check accepts ``True``/``False``. Centralising the guard keeps
    the rationale in one place.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def swap_ordering_field(
    user: User, model: type[Model], order_field: str, id_a: int, id_b: int
) -> tuple | None:
    """Atomically exchange one ordering field on two user-owned rows.

    ``None`` means at least one id was missing or belonged to another user.
    The user row lock serializes read-modify-write reorder operations for a
    single account, and locking the two target rows serializes the swap
    against a concurrent detail-view delete — both on databases that support
    ``select_for_update`` (no-op on SQLite, where ``atomic()`` alone gives
    all-or-nothing).
    """
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        try:
            # Lock both target rows for the transaction. The user-row lock
            # above serializes swap-vs-swap for one account; locking the rows
            # too serializes swap-vs-delete uniformly across models. The Rule
            # detail DELETE also takes the user lock, but the TravelRule detail
            # DELETE does not, so without a row lock a concurrent travel-rule
            # delete could half-apply a swap. With it, a concurrent delete of a
            # target either blocks until the swap commits or makes this get()
            # raise DoesNotExist -> clean 404, never a half-applied swap. No-op
            # on SQLite (whole-db write lock via atomic()).
            row_a = model.objects.select_for_update().get(pk=id_a, user=user)
            row_b = model.objects.select_for_update().get(pk=id_b, user=user)
        except model.DoesNotExist:
            return None

        value_a = getattr(row_a, order_field)
        value_b = getattr(row_b, order_field)
        setattr(row_a, order_field, value_b)
        setattr(row_b, order_field, value_a)
        model.objects.bulk_update([row_a, row_b], [order_field])
        # No refresh_from_db: bulk_update persists the in-memory values
        # verbatim (no DB default/trigger on the ordering field), so the
        # rows already hold the swapped values. Mirrors 0046 compaction.
        return row_a, row_b


def parse_swap_body(request, *, noun: str) -> tuple[int, int] | JsonResponse:
    """Parse a swap body {"a","b"}; return (id_a, id_b) or a 4xx JsonResponse."""
    data, error = parse_json_object(request)
    if error is not None:
        return error
    id_a = data.get("a")
    id_b = data.get("b")
    if not is_plain_int(id_a) or not is_plain_int(id_b) or id_a == id_b:
        return JsonResponse(
            {"errors": {"body": f"a and b must be distinct integer {noun} ids."}},
            status=400,
        )
    return id_a, id_b


def parse_time_or_error(field_name, value, block_id=None):
    """Parse an HH:MM string. Return ``(time, None)`` on success or
    ``(None, JsonResponse)`` with a 400 error on failure.

    ``block_id`` is appended to the error message when supplied so callers
    handling lists of entries can disambiguate which one was malformed.
    """
    try:
        return time_validation.parse_time_field(field_name, value, block_id=block_id), None
    except time_validation.TimeValidationError as error:
        return None, _time_error_response(error)


def _time_error_response(error):
    return JsonResponse({"errors": {error.field: error.message}}, status=400)


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
    try:
        start, end = time_validation.validate_block_times(
            start_str, end_str, block_id=block_id, enforce_granularity=enforce_granularity
        )
    except time_validation.TimeValidationError as error:
        return None, None, _time_error_response(error)
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
                    "sort_order": (f"sort_order must be between 0 and {MAX_SORT_ORDER}{suffix}.")
                }
            },
            status=400,
        )
    return None
