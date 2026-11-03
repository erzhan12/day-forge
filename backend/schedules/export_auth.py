"""Restricted Bearer authentication for the daily export API only (feature 0088).

A personal export token authenticates reads on the export views alone,
through this module's explicit per-view check. It is never wired into
``AUTHENTICATION_BACKENDS`` or middleware, so it can never authenticate any
other route, call Django ``login()``, or establish a session.
"""

from django.http import JsonResponse

from schedules.export_tokens import authenticate as authenticate_export_token

_BEARER_PREFIX = "Bearer "


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
