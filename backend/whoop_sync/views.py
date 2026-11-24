"""WHOOP OAuth connect / callback (feature 0107).

  - GET /api/whoop/connect/   — login required; 302 → WHOOP consent
  - GET /api/whoop/callback/  — login required; code → tokens, upsert, plain page
  - GET /api/export/whoop/<date>/ — Bearer export token or session; Markdown

There is no Settings UI in the MVP (D4), so the callback answers with a
plain-text "WHOOP connected" / "WHOOP connection failed" page instead of a
redirect. WHOOP's ``state`` is only 8 characters (32 bits); that is
acceptable only because it is bound to the session, popped before it is
compared (single use) and compared with ``secrets.compare_digest``.
"""

import logging
import secrets

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from schedules.export_api import _error, _parse_date
from schedules.export_auth import resolve_export_owner
from schedules.window import user_time_zone_readonly

from whoop_sync import service
from whoop_sync.day import load_day
from whoop_sync.formatting import format_whoop_day
from whoop_sync.models import WhoopAccount

logger = logging.getLogger(__name__)

SESSION_STATE_KEY = "whoop_oauth_state"
CONNECTED = "WHOOP connected"
FAILED = "WHOOP connection failed"
NOT_CONFIGURED = "WHOOP is not configured"


def _plain(text: str, status: int) -> HttpResponse:
    response = HttpResponse(text, status=status, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET"])
def connect(request: HttpRequest) -> HttpResponse:
    if not service.is_configured():
        return _plain(NOT_CONFIGURED, 503)
    state = secrets.token_hex(service.STATE_LENGTH // 2)
    request.session[SESSION_STATE_KEY] = state
    return HttpResponseRedirect(service.build_authorization_url(state))


@login_required
@require_http_methods(["GET"])
def callback(request: HttpRequest) -> HttpResponse:
    # Pop first so a state is single-use whatever happens next.
    session_state = request.session.pop(SESSION_STATE_KEY, None)
    if not service.is_configured():
        return _plain(NOT_CONFIGURED, 503)

    query_state = request.GET.get("state")
    if (
        not isinstance(session_state, str)
        or not query_state
        or not secrets.compare_digest(query_state, session_state)
    ):
        logger.info("WHOOP callback rejected (state) for user %s", request.user.id)
        return _plain(FAILED, 400)
    if request.GET.get("error"):
        logger.info("WHOOP callback rejected (denied) for user %s", request.user.id)
        return _plain(FAILED, 400)
    code = request.GET.get("code")
    if not code:
        logger.info("WHOOP callback rejected (missing code) for user %s", request.user.id)
        return _plain(FAILED, 400)

    # Catch broadly: any failure must end on the failure page, not a 500.
    # Only the exception class is logged — never the code, tokens or body.
    try:
        grant = service.exchange_code(code)
    except Exception as exc:
        logger.warning(
            "WHOOP code exchange failed for user %s (%s)", request.user.id, type(exc).__name__
        )
        return _plain(FAILED, 502)

    with transaction.atomic():
        account, _ = WhoopAccount.objects.get_or_create(user=request.user)
        account.set_refresh_token(grant.refresh_token)
        account.set_access_token(grant.access_token)
        account.access_token_expiry = grant.expiry
        account.scopes = grant.scopes
        account.last_verified_at = timezone.now()
        account.save()
    return _plain(CONNECTED, 200)


# ----- Export read: GET /api/export/whoop/<date>/ --------------------------

_EXPORT_ERRORS = (
    (service.WhoopAuthError, 409, "WHOOP needs to be reconnected."),
    (ImproperlyConfigured, 409, "WHOOP needs to be reconnected."),
    (service.WhoopRateLimitError, 429, "WHOOP rate limit reached. Try again later."),
    (service.WhoopProviderError, 502, "WHOOP is unavailable. Try again later."),
    (OperationalError, 502, "WHOOP is unavailable. Try again later."),
)
_EXPORT_EXCEPTION_TYPES = tuple(error for error, _, _ in _EXPORT_ERRORS)


@require_http_methods(["GET"])
def whoop_export(request: HttpRequest, date: str) -> HttpResponse:
    """Markdown WHOOP summary for one date (feature 0107).

    Authenticates exactly like the daily export (Bearer export token or an
    active session) and shares its date parsing. Every response is
    ``private, no-store``; WHOOP data is not stored, cached or logged, and
    provider bodies never reach the client.
    """
    owner, error_response = resolve_export_owner(request)
    if error_response is not None:
        return error_response
    parsed_date, error_response = _parse_date(date, owner)
    if error_response is not None:
        return error_response
    if not service.is_configured():
        return _error("WHOOP is not configured.", 404)
    account = WhoopAccount.objects.filter(user=owner).first()
    if account is None:
        return _error("WHOOP is not connected.", 404)

    try:
        markdown = format_whoop_day(
            load_day(account, parsed_date, user_time_zone_readonly(owner))
        )
    except _EXPORT_EXCEPTION_TYPES as exc:
        status, detail = next((s, d) for e, s, d in _EXPORT_ERRORS if isinstance(exc, e))
        logger.info("WHOOP export failed for user %s (%s)", owner.pk, type(exc).__name__)
        return _error(detail, status)

    response = HttpResponse(markdown, content_type="text/markdown; charset=utf-8")
    response["Cache-Control"] = "private, no-store"
    return response
