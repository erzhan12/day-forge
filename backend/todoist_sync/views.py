"""Todoist endpoints.

Three URL paths, five method handlers:

  - GET    /api/todoist/account/                  — status (connected + last_verified_at)
  - POST   /api/todoist/account/                  — verify + persist (upsert)
  - DELETE /api/todoist/account/                  — disconnect
  - GET    /api/todoist/tasks/<date>/             — fetch tasks (cached; ?refresh=1 bypasses)
  - POST   /api/todoist/tasks/<id>/complete/      — complete a task

All non-2xx responses use the envelope ``{"errors": {"detail": ...}}``
to match ``frontend/src/composables/useHttp.ts:77``.
"""

import datetime
import logging

from common.http import parse_json_object
from common.integration_response import resource_error, resource_meta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from schedules.ratelimit import (
    connect_rate_limit_key,
    consume_rate_limit,
    rate_limited_response,
)
from schedules.window import get_schedule_settings, resolve_time_zone

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
            account.last_verified_at.isoformat() if account.last_verified_at else None
        ),
    }


def _service_error_response(
    exc: Exception, *, resource: bool = False, account_state: str = "connected"
) -> JsonResponse:
    """Map ``TodoistError`` subclasses to the standard envelope + status."""
    for cls, (status, detail) in _SERVICE_ERROR_STATUS.items():
        if isinstance(exc, cls):
            if resource:
                state = (
                    "credentials_error"
                    if status == 401
                    else "unavailable"
                    if status == 504
                    else "provider_error"
                )
                return resource_error(
                    detail, status, account_state=account_state, resource_state=state
                )
            return _envelope(detail, status)
    # Unknown error class — log and return 500. Never let the raw error
    # bubble to the client; provider stacktraces can include the token in
    # some code paths.
    logger.exception("Unexpected Todoist service error")
    if resource:
        return resource_error(
            "Todoist error",
            500,
            account_state=account_state,
            resource_state="unavailable",
        )
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
    data, err = parse_json_object(request, allow_empty=True, error_field="detail")
    if err is not None:
        return err

    cleaned, errors = validate_account_payload(data)
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    key = connect_rate_limit_key("todoist", request.user.id)
    if not consume_rate_limit(key, settings.TODOIST_CONNECT_RATE_LIMIT_PER_HOUR):
        return rate_limited_response()

    try:
        service.verify_credentials(cleaned["token"])
    except service.TodoistError as e:
        return _service_error_response(
            e,
            resource=True,
            account_state=(
                "connected"
                if TodoistAccount.objects.filter(user=request.user).exists()
                else "disconnected"
            ),
        )

    try:
        with transaction.atomic():
            acc, _ = TodoistAccount.objects.select_for_update().get_or_create(
                user=request.user,
            )
            # BinaryField cannot be passed inline through get_or_create.
            acc.set_token(cleaned["token"])
            acc.last_verified_at = timezone.now()
            # Plain save bumps the cache-key version via auto_now.
            acc.save()
    except ImproperlyConfigured:
        logger.exception("Todoist encryption misconfigured for user %s", request.user.id)
        return resource_error(
            "Todoist service is misconfigured. Contact the administrator.",
            500,
            account_state="configuration_error",
            resource_state="unavailable",
        )

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
        return resource_error(
            "No Todoist account configured",
            503,
            account_state="disconnected",
            resource_state="unavailable",
        )

    # One saved-zone and clock snapshot controls both the provider query and
    # cache identity, even if settings change while the provider is in flight.
    time_zone = get_schedule_settings(request.user).time_zone
    local_today = timezone.localtime(timezone.now(), resolve_time_zone(time_zone)).date()
    # ``?refresh=1`` bypasses the cache and re-warms the current scope.
    force_refresh = request.GET.get("refresh") == "1"
    filter_scope = todoist_cache.tasks_filter_scope(parsed_date, local_today=local_today)

    if not force_refresh:
        cached = todoist_cache.get_cached_tasks(
            account_row, parsed_date, time_zone=time_zone, filter_scope=filter_scope
        )
        if cached is not None:
            return JsonResponse({"tasks": cached, "meta": resource_meta("connected", "ready")})

    try:
        tasks_list = service.fetch_tasks_for_date(
            account_row,
            parsed_date,
            local_today=local_today,
        )
    except ImproperlyConfigured:
        # Server-side encryption-key issue (e.g. TODOIST_ENCRYPTION_KEY
        # rotated while old rows persist). Surface as a 500 with a
        # config-shaped message instead of letting it be masked as a
        # 502 "Todoist provider failure" — ops can act on the real cause
        # faster.
        logger.exception("Todoist decryption misconfigured for user %s", request.user.id)
        return resource_error(
            "Todoist service is misconfigured. Contact the administrator.",
            500,
            account_state="configuration_error",
            resource_state="unavailable",
        )
    except service.TodoistError as e:
        return _service_error_response(e, resource=True)

    payload = [normalized_task_to_dict(t) for t in tasks_list]
    todoist_cache.set_cached_tasks(
        account_row, parsed_date, payload, time_zone=time_zone, filter_scope=filter_scope
    )
    return JsonResponse({"tasks": payload, "meta": resource_meta("connected", "ready")})


# ----- /api/todoist/tasks/<task_id>/complete/ ----------------------------


@login_required
@require_http_methods(["POST"])
def complete(request: HttpRequest, task_id: str) -> JsonResponse:
    # Explicit ordering so the 503-vs-anything-else precedence is
    # deterministic and testable:
    #   1) resolve the account (503 if absent),
    #   2) call the service (try ladder below).
    # The view parses NO request body — the id is in the URL path — so there
    # is no oversized-body guard here (unlike POST /account/, which
    # json.loads(request.body)). Django's global DATA_UPLOAD_MAX_MEMORY_SIZE
    # already caps any stray body at the WSGI/ASGI boundary.
    try:
        account_row = request.user.todoist_account
    except TodoistAccount.DoesNotExist:
        return resource_error(
            "No Todoist account configured",
            503,
            account_state="disconnected",
            resource_state="unavailable",
        )

    try:
        service.complete_task(account_row, task_id)
    except ImproperlyConfigured:
        # Server-side encryption-key issue (e.g. TODOIST_ENCRYPTION_KEY
        # rotated while old rows persist) — config-shaped 500, not a 502
        # that would wrongly point ops at Todoist. Mirrors the ``tasks`` view.
        logger.exception("Todoist decryption misconfigured for user %s", request.user.id)
        return resource_error(
            "Todoist service is misconfigured. Contact the administrator.",
            500,
            account_state="configuration_error",
            resource_state="unavailable",
        )
    except service.TodoistError as e:
        return _service_error_response(e, resource=True)

    # Invalidate every cached list for this user (versioned-key bump) so the
    # just-closed task is not served from a stale cache for up to the TTL.
    # A bare ack is sufficient — the frontend already removed the row
    # optimistically, so returning the refreshed list (a second provider
    # round-trip) would be wasted work.
    todoist_cache.invalidate_tasks(account_row)
    return JsonResponse({"ok": True})
