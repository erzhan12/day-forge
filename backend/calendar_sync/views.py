"""CalDAV / Apple Calendar endpoints.

Three URL paths, four method handlers:

  - GET    /api/calendar/account/         — status + default_base_url
  - POST   /api/calendar/account/         — verify + persist (upsert)
  - DELETE /api/calendar/account/         — disconnect
  - GET    /api/calendar/events/<date>/   — fetch events (cached; ?refresh=1 bypasses)

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
from schedules.window import get_schedule_settings

from calendar_sync import cache as calendar_cache
from calendar_sync import service
from calendar_sync.models import CalDAVAccount
from calendar_sync.schemas import (
    normalized_event_to_dict,
    validate_account_payload,
)

logger = logging.getLogger(__name__)

_SERVICE_ERROR_STATUS = {
    service.CalDAVAuthError: (401, "Invalid Apple Calendar credentials"),
    service.CalDAVTimeoutError: (504, "Apple Calendar request timed out"),
    service.CalDAVProviderError: (502, "Apple Calendar provider failure"),
}


def _envelope(detail: str, status: int, **extra) -> JsonResponse:
    body = {"errors": {"detail": detail, **extra}}
    return JsonResponse(body, status=status)


def _account_status_payload(account: CalDAVAccount | None) -> dict:
    """Status payload — never includes a password field of any shape."""
    if account is None:
        return {
            "connected": False,
            "apple_id": None,
            "base_url": None,
            "last_verified_at": None,
            "default_base_url": settings.CALDAV_DEFAULT_BASE_URL,
        }
    return {
        "connected": True,
        "apple_id": account.apple_id,
        "base_url": account.base_url,
        "last_verified_at": (
            account.last_verified_at.isoformat() if account.last_verified_at else None
        ),
        "default_base_url": settings.CALDAV_DEFAULT_BASE_URL,
    }


def _service_error_response(
    exc: Exception, *, resource: bool = False, account_state: str = "connected"
) -> JsonResponse:
    """Map ``CalDAVError`` subclasses to the standard envelope + status."""
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
    # bubble to the client; CalDAV stacktraces can include the URL with
    # credentials in some lib versions.
    logger.exception("Unexpected CalDAV service error")
    if resource:
        return resource_error(
            "Apple Calendar error",
            500,
            account_state=account_state,
            resource_state="unavailable",
        )
    return _envelope("Apple Calendar error", 500)


# ----- /api/calendar/account/ --------------------------------------------


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def account(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        try:
            acc = request.user.caldav_account
        except CalDAVAccount.DoesNotExist:
            acc = None
        return JsonResponse(_account_status_payload(acc))

    if request.method == "DELETE":
        # Idempotent delete. ``filter().delete()`` returns ``(count, ...)``;
        # we don't surface that — the response shape is identical whether
        # an account existed or not. Versioned cache keys mean prior
        # entries become unreachable automatically (no `cache.delete`
        # enumeration needed); they expire via TTL.
        CalDAVAccount.objects.filter(user=request.user).delete()
        return JsonResponse(_account_status_payload(None))

    # POST — verify-then-upsert.
    data, err = parse_json_object(request, allow_empty=True, error_field="detail")
    if err is not None:
        return err

    cleaned, errors = validate_account_payload(data)
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    base_url = cleaned["base_url"] or settings.CALDAV_DEFAULT_BASE_URL

    key = connect_rate_limit_key("caldav", request.user.id)
    if not consume_rate_limit(key, settings.CALDAV_CONNECT_RATE_LIMIT_PER_HOUR):
        return rate_limited_response()

    try:
        service.verify_credentials(cleaned["apple_id"], cleaned["password"], base_url)
    except service.CalDAVError as e:
        return _service_error_response(
            e,
            resource=True,
            account_state=(
                "connected"
                if CalDAVAccount.objects.filter(user=request.user).exists()
                else "disconnected"
            ),
        )

    try:
        with transaction.atomic():
            acc, _ = CalDAVAccount.objects.select_for_update().get_or_create(
                user=request.user,
                defaults={"apple_id": cleaned["apple_id"], "base_url": base_url},
            )
            acc.apple_id = cleaned["apple_id"]
            acc.base_url = base_url
            acc.last_verified_at = timezone.now()
            acc.set_password(cleaned["password"])
            # Plain save bumps the cache-key version via auto_now.
            acc.save()
    except ImproperlyConfigured:
        logger.exception("CalDAV encryption misconfigured for user %s", request.user.id)
        return resource_error(
            "Calendar service is misconfigured. Contact the administrator.",
            500,
            account_state="configuration_error",
            resource_state="unavailable",
        )

    return JsonResponse(_account_status_payload(acc))


# ----- /api/calendar/events/<date>/ --------------------------------------


@login_required
@require_http_methods(["GET"])
def events(request: HttpRequest, date: str) -> JsonResponse:
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return _envelope("Invalid date format. Use YYYY-MM-DD.", 400)

    try:
        account_row = request.user.caldav_account
    except CalDAVAccount.DoesNotExist:
        return resource_error(
            "No CalDAV account configured",
            503,
            account_state="disconnected",
            resource_state="unavailable",
        )

    # One saved timezone snapshot drives cache lookup, provider bounds and
    # serialization for this request, even if settings change mid-fetch.
    time_zone = get_schedule_settings(request.user).time_zone

    # ``?refresh=1`` forces a cache-bypass live re-fetch (manual Refresh /
    # background poll). Additive: a non-forced read still hits the cache,
    # and the forced read re-warms it below.
    force_refresh = request.GET.get("refresh") == "1"

    if not force_refresh:
        cached = calendar_cache.get_cached_events(account_row, parsed_date, time_zone)
        if cached is not None:
            return JsonResponse({"events": cached, "meta": resource_meta("connected", "ready")})

    try:
        events_list = service.fetch_events_for_date(account_row, parsed_date, time_zone)
    except ImproperlyConfigured:
        # Server-side encryption-key issue (e.g. CALDAV_ENCRYPTION_KEY
        # rotated while old rows persist). Surface as a 500 with a
        # config-shaped message instead of letting it be masked as a
        # 502 "Apple Calendar provider failure" — ops can act on the
        # real cause faster.
        logger.exception("CalDAV decryption misconfigured for user %s", request.user.id)
        return resource_error(
            "Calendar service is misconfigured. Contact the administrator.",
            500,
            account_state="configuration_error",
            resource_state="unavailable",
        )
    except service.CalDAVError as e:
        return _service_error_response(e, resource=True)

    payload = [normalized_event_to_dict(e) for e in events_list]
    calendar_cache.set_cached_events(account_row, parsed_date, payload, time_zone)
    return JsonResponse({"events": payload, "meta": resource_meta("connected", "ready")})
