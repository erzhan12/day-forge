"""Todoist endpoints.

Two URL paths, four method handlers:

  - GET    /api/todoist/account/        — status (connected + last_verified_at)
  - POST   /api/todoist/account/        — verify + persist (upsert)
  - DELETE /api/todoist/account/        — disconnect
  - GET    /api/todoist/tasks/<date>/   — fetch tasks (cached)

All non-2xx responses use the envelope ``{"errors": {"detail": ...}}``
to match ``frontend/src/composables/useHttp.ts:77``.
"""

import datetime
import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from schedules.http import reject_oversized_body

from todoist_sync import cache as todoist_cache
from todoist_sync import service
from todoist_sync.models import TodoistAccount
from todoist_sync.schemas import (
    normalized_task_to_dict,
    validate_account_payload,
)

logger = logging.getLogger(__name__)

_SERVICE_ERROR_STATUS = {
    service.TodoistAuthError: (401, "Invalid Todoist credentials"),
    service.TodoistTimeoutError: (504, "Todoist request timed out"),
    service.TodoistProviderError: (502, "Todoist provider failure"),
}


def _envelope(detail: str, status: int, **extra) -> JsonResponse:
    body = {"errors": {"detail": detail, **extra}}
    return JsonResponse(body, status=status)


def _account_status_payload(account: TodoistAccount | None) -> dict:
    """Status payload — never includes a token field of any shape."""
    if account is None:
        return {
            "connected": False,
            "last_verified_at": None,
        }
    return {
        "connected": True,
        "last_verified_at": (
            account.last_verified_at.isoformat()
            if account.last_verified_at
            else None
        ),
    }


def _service_error_response(exc: Exception) -> JsonResponse:
    """Map ``TodoistError`` subclasses to the standard envelope + status."""
    for cls, (status, detail) in _SERVICE_ERROR_STATUS.items():
        if isinstance(exc, cls):
            return _envelope(detail, status)
    # Unknown error class — log and return 500. Never let the raw error
    # bubble to the client; provider stacktraces can include the token in
    # some code paths.
    logger.exception("Unexpected Todoist service error")
    return _envelope("Todoist error", 500)


# ----- /api/todoist/account/ ---------------------------------------------


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def account(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        try:
            acc = request.user.todoist_account
        except TodoistAccount.DoesNotExist:
            acc = None
        return JsonResponse(_account_status_payload(acc))

    if request.method == "DELETE":
        # Idempotent delete. ``filter().delete()`` returns ``(count, ...)``;
        # we don't surface that — the response shape is identical whether
        # an account existed or not. Versioned cache keys mean prior
        # entries become unreachable automatically (no `cache.delete`
        # enumeration needed); they expire via TTL.
        TodoistAccount.objects.filter(user=request.user).delete()
        return JsonResponse(_account_status_payload(None))

    # POST — verify-then-upsert.
    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _envelope("Invalid JSON.", 400)

    cleaned, errors = validate_account_payload(data)
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    try:
        service.verify_credentials(cleaned["token"])
    except service.TodoistError as e:
        return _service_error_response(e)

    with transaction.atomic():
        acc, _ = TodoistAccount.objects.select_for_update().get_or_create(
            user=request.user,
        )
        # ``token_encrypted`` is a ``BinaryField`` and cannot be passed
        # inline / via ``defaults`` — set it on the instance after the row
        # exists.
        acc.set_token(cleaned["token"])
        acc.last_verified_at = timezone.now()
        # Plain save — no ``update_fields`` — so ``auto_now=True`` fires
        # on ``updated_at`` and the cache-key version advances. See the
        # auto_now footgun note in todoist_sync/cache.py.
        acc.save()

    return JsonResponse(_account_status_payload(acc))


# ----- /api/todoist/tasks/<date>/ ----------------------------------------


@login_required
@require_http_methods(["GET"])
def tasks(request: HttpRequest, date: str) -> JsonResponse:
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return _envelope("Invalid date format. Use YYYY-MM-DD.", 400)

    try:
        account_row = request.user.todoist_account
    except TodoistAccount.DoesNotExist:
        return _envelope("No Todoist account configured", 503)

    include_overdue_carryover = request.GET.get("carry_overdue") == "1"
    filter_scope = todoist_cache.tasks_filter_scope(
        parsed_date, include_overdue_carryover=include_overdue_carryover
    )

    cached = todoist_cache.get_cached_tasks(
        account_row, parsed_date, filter_scope=filter_scope
    )
    if cached is not None:
        return JsonResponse({"tasks": cached})

    try:
        tasks_list = service.fetch_tasks_for_date(
            account_row,
            parsed_date,
            include_overdue_carryover=include_overdue_carryover,
        )
    except ImproperlyConfigured:
        # Server-side encryption-key issue (e.g. TODOIST_ENCRYPTION_KEY
        # rotated while old rows persist). Surface as a 500 with a
        # config-shaped message instead of letting it be masked as a
        # 502 "Todoist provider failure" — ops can act on the real cause
        # faster.
        logger.exception("Todoist decryption misconfigured for user %s", request.user.id)
        return _envelope(
            "Todoist service is misconfigured. Contact the administrator.",
            500,
        )
    except service.TodoistError as e:
        return _service_error_response(e)

    payload = [normalized_task_to_dict(t) for t in tasks_list]
    todoist_cache.set_cached_tasks(
        account_row, parsed_date, payload, filter_scope=filter_scope
    )
    return JsonResponse({"tasks": payload})
