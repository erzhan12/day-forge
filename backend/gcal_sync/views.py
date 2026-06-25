"""Google Calendar OAuth + events endpoints (feature 0022).

Five URL paths under ``/api/calendar/google/``:

  - GET    /api/calendar/google/connect/              — 302 → Google consent
  - GET    /api/calendar/google/callback/             — code→token, upsert, 302 → Settings
  - GET    /api/calendar/google/accounts/             — list connected accounts
  - DELETE /api/calendar/google/accounts/<id>/        — disconnect one account
  - GET    /api/calendar/google/events/<date>/        — async multi-account fetch

All non-2xx JSON responses use the envelope ``{"errors": {"detail": ...}}``
to match ``frontend/src/composables/useHttp.ts``. The connect/callback views
redirect (302) to ``/settings/?google=...`` instead of returning JSON.
"""

import asyncio
import datetime
import logging
import secrets

from calendar_sync.schemas import normalized_event_to_dict
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import HttpRequest, HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from gcal_sync import cache as gcal_cache
from gcal_sync import service
from gcal_sync.models import GoogleCalendarAccount

logger = logging.getLogger(__name__)

_SERVICE_ERROR_STATUS = {
    service.GoogleCalAuthError: (401, "Google authorization failed"),
    service.GoogleCalTimeoutError: (504, "Google Calendar request timed out"),
    service.GoogleCalProviderError: (502, "Google Calendar provider failure"),
}

_CONFIG_500_DETAIL = (
    "Google Calendar service is misconfigured. Contact the administrator."
)


def _envelope(detail: str, status: int, **extra) -> JsonResponse:
    body = {"errors": {"detail": detail, **extra}}
    return JsonResponse(body, status=status)


def _accounts_payload(user) -> list[dict]:
    """Connected-account list — never includes a token field of any shape."""
    return [
        {
            "id": acc.id,
            "email": acc.email,
            "last_verified_at": (
                acc.last_verified_at.isoformat()
                if acc.last_verified_at
                else None
            ),
        }
        for acc in GoogleCalendarAccount.objects.filter(user=user).order_by(
            "email", "id"
        )
    ]


# ----- OAuth connect / callback (sync) -----------------------------------


@login_required
@require_http_methods(["GET"])
def connect(request: HttpRequest) -> HttpResponseRedirect:
    state = secrets.token_urlsafe(32)
    request.session["gcal_oauth_state"] = state
    url = service.build_authorization_url(state)
    return HttpResponseRedirect(url)


@login_required
@require_http_methods(["GET"])
def callback(request: HttpRequest) -> HttpResponseRedirect:
    # 1) State CSRF guard. Pop so a state can't be replayed; reject on
    #    missing query state, missing session state, or mismatch.
    query_state = request.GET.get("state")
    session_state = request.session.pop("gcal_oauth_state", None)
    if not query_state or not session_state or query_state != session_state:
        return HttpResponseRedirect("/settings/?google=error&reason=state")

    # 2) Google-returned error (e.g. user denied), then missing-code guard.
    if request.GET.get("error"):
        return HttpResponseRedirect("/settings/?google=error&reason=denied")
    code = request.GET.get("code")
    if not code:
        return HttpResponseRedirect(
            "/settings/?google=error&reason=missing_code"
        )

    # 3) Exchange code → tokens + identity (sync; this view stays sync).
    #    Catch broadly (not just GoogleCalError): an unexpected failure inside
    #    exchange_code (e.g. a non-JSON provider body, a missing id_token
    #    claim) must still redirect to the provider-error page, not surface a
    #    raw 500. logger.exception preserves the traceback for diagnosis; the
    #    code/token are never in the message.
    try:
        info = service.exchange_code(code, query_state)
    except Exception:
        logger.exception(
            "Google OAuth code exchange failed for user %s", request.user.id
        )
        return HttpResponseRedirect("/settings/?google=error&reason=provider")

    # 4) Upsert under a row lock. Uniqueness (user, google_account_id) makes
    #    reconnect idempotent. Plain save() → auto_now → cache version rotates.
    with transaction.atomic():
        acc, _ = (
            GoogleCalendarAccount.objects.select_for_update().get_or_create(
                user=request.user,
                google_account_id=info["google_account_id"],
                defaults={"email": info["email"]},
            )
        )
        acc.email = info["email"]
        acc.set_refresh_token(info["refresh_token"])
        if info.get("access_token"):
            acc.set_access_token(info["access_token"])
        acc.access_token_expiry = info.get("expiry")
        acc.last_verified_at = timezone.now()
        acc.save()

    return HttpResponseRedirect("/settings/?google=connected")


# ----- Account list / disconnect (sync) ----------------------------------


@login_required
@require_http_methods(["GET"])
def accounts(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"accounts": _accounts_payload(request.user)})


@login_required
@require_http_methods(["DELETE"])
def account_detail(request: HttpRequest, account_id: int) -> JsonResponse:
    # Scoped to request.user (IDOR guard); idempotent. Versioned cache keys
    # make prior entries unreachable. Returns the refreshed list.
    GoogleCalendarAccount.objects.filter(
        user=request.user, id=account_id
    ).delete()
    return JsonResponse({"accounts": _accounts_payload(request.user)})


# ----- Events (async multi-account fetch) --------------------------------


@login_required
@require_http_methods(["GET"])
async def events(request: HttpRequest, date: str) -> JsonResponse:
    # ``datetime.date`` module-qualified to avoid shadowing the ``date`` route
    # param. Parse to a real date — never pass the raw string downstream.
    try:
        target_date = datetime.date.fromisoformat(date)
    except ValueError:
        return _envelope("Invalid date format. Use YYYY-MM-DD.", 400)

    # Resolve the user via auser() FIRST — touching the sync request.user
    # proxy in an async body raises SynchronousOnlyOperation.
    user = await request.auser()

    accounts_list = [
        acc async for acc in GoogleCalendarAccount.objects.filter(user=user)
    ]
    if not accounts_list:
        return _envelope("No Google Calendar account configured", 503)

    merged: list[dict] = []
    account_errors: list[dict] = []

    # Cache hits go straight into the merged list; misses are fetched.
    pending: list = []
    for acc in accounts_list:
        cached = await gcal_cache.get_cached_events(acc, target_date)
        if cached is not None:
            merged.extend(cached)
        else:
            pending.append(acc)

    results = await asyncio.gather(
        *[service.fetch_events_for_account(acc, target_date) for acc in pending],
        return_exceptions=True,
    )

    # A server-wide key-rotation problem (ImproperlyConfigured) is not
    # per-account — short-circuit the whole response to a config-500.
    for result in results:
        if isinstance(result, ImproperlyConfigured):
            logger.exception(
                "Google decryption misconfigured for user %s",
                user.id,
                exc_info=result,
            )
            return _envelope(_CONFIG_500_DETAIL, 500)

    for acc, result in zip(pending, results):
        if isinstance(result, service.GoogleCalAuthError):
            account_errors.append(
                {
                    "account_id": acc.id,
                    "email": acc.email,
                    "error": "reconnect_required",
                }
            )
        elif isinstance(
            result, (service.GoogleCalTimeoutError, service.GoogleCalProviderError)
        ):
            account_errors.append(
                {"account_id": acc.id, "email": acc.email, "error": "unavailable"}
            )
        elif isinstance(result, BaseException):
            # Unknown failure — never blank the panel; log and mark this one
            # account unavailable so the healthy accounts still render.
            logger.error(
                "Unexpected Google fetch error for account %s",
                acc.id,
                exc_info=result,
            )
            account_errors.append(
                {"account_id": acc.id, "email": acc.email, "error": "unavailable"}
            )
        else:
            payload = [normalized_event_to_dict(ev) for ev in result]
            await gcal_cache.set_cached_events(acc, target_date, payload)
            merged.extend(payload)

    # Final merge sort by (start, title, external_uid) — ISO-8601 UTC start
    # strings sort chronologically, matching the per-account server sort.
    merged.sort(key=lambda e: (e["start"], e["title"], e["external_uid"]))
    return JsonResponse({"events": merged, "account_errors": account_errors})
