"""WHOOP OAuth connect / callback (feature 0107).

  - GET /api/whoop/connect/   — login required; 302 → WHOOP consent
  - GET /api/whoop/callback/  — login required; code → tokens, upsert, plain page

There is no Settings UI in the MVP (D4), so the callback answers with a
plain-text "WHOOP connected" / "WHOOP connection failed" page instead of a
redirect. WHOOP's ``state`` is only 8 characters (32 bits); that is
acceptable only because it is bound to the session, popped before it is
compared (single use) and compared with ``secrets.compare_digest``.
"""

import logging
import secrets

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from whoop_sync import service
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
        account = WhoopAccount.objects.filter(user=request.user).first()
        if account is None:
            account = WhoopAccount(user=request.user)
        account.set_refresh_token(grant.refresh_token)
        account.set_access_token(grant.access_token)
        account.access_token_expiry = grant.expiry
        account.scopes = grant.scopes
        account.last_verified_at = timezone.now()
        account.save()
    return _plain(CONNECTED, 200)
