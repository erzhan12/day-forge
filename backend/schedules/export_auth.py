"""Restricted Bearer authentication for the read-only export routes.

A personal export token (feature 0088) authenticates reads on exactly the
routes named in ``BEARER_ROUTE_NAMES``, through this module's explicit
per-view check: the daily schedule export and, since feature 0107, the WHOOP
morning summary (health data). It is never wired into
``AUTHENTICATION_BACKENDS`` or middleware, so it can never authenticate any
other route, call Django ``login()``, or establish a session.
"""

from django.http import JsonResponse

from schedules.export_tokens import authenticate as authenticate_export_token

_BEARER_PREFIX = "Bearer "

# The only URL names whose views call ``resolve_export_owner``. Widening this
# set widens what a leaked export token can read: review it as a security
# change. ``tests/test_daily_export_api.py`` builds its Bearer matrix
# exclusions from this constant.
BEARER_ROUTE_NAMES = frozenset({"daily_export", "whoop_export"})


def _unauthorized() -> JsonResponse:
    response = JsonResponse({"errors": {"detail": "Authentication required."}}, status=401)
    response["Cache-Control"] = "private, no-store"
    return response


def resolve_export_owner(request):
    """Return ``(user, None)`` on success or ``(None, response)`` on failure.

    An ``Authorization`` header takes precedence over any session and must
    be a valid, active-owner Bearer credential — a missing/malformed/
    invalid/revoked value returns 401 even when a session exists. Without
    that header, an active authenticated session is accepted. Otherwise:
    401 JSON, never a login redirect. Query parameters are never consulted.
    """
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header:
        if not header.startswith(_BEARER_PREFIX):
            return None, _unauthorized()
        raw_token = header[len(_BEARER_PREFIX):].strip()
        owner = authenticate_export_token(raw_token)
        if owner is None:
            return None, _unauthorized()
        return owner, None

    if request.user.is_authenticated and request.user.is_active:
        return request.user, None
    return None, _unauthorized()
