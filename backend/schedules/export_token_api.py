"""Session-only token-management API for the personal daily-export
credential (feature 0088): ``GET``/``POST``/``DELETE /api/user/export-token/``.

A Bearer export credential authorizes export reads but must never manage
itself: any ``Authorization`` header on this endpoint is rejected, even
when a valid session is also present, so a leaked token alone can never
mint a replacement or discover whether one already exists.
"""

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.export_tokens import TokenExistsError, create_token, revoke_token
from schedules.models import PersonalExportToken
from schedules.mutations import ScheduleChanged, schedule_changed_response


def _response(payload: dict, *, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "private, no-store"
    return response


def _unauthorized() -> JsonResponse:
    return _response({"errors": {"detail": "Authentication required."}}, status=401)


def _status_payload(user) -> dict:
    token = PersonalExportToken.objects.filter(user=user).first()
    return {
        "has_token": token is not None,
        "created_at": token.created_at.isoformat() if token else None,
    }


@require_http_methods(["GET", "POST", "DELETE"])
def export_token(request):
    # Reject any Bearer credential outright — this endpoint is session-only,
    # never token-authenticated, regardless of whether a session also exists.
    if request.META.get("HTTP_AUTHORIZATION"):
        return _unauthorized()
    if not (request.user.is_authenticated and request.user.is_active):
        return _unauthorized()

    if request.method == "GET":
        return _response(_status_payload(request.user))

    if request.method == "DELETE":
        try:
            revoke_token(request.user.pk)
        except ScheduleChanged as exc:
            response = schedule_changed_response(exc)
            response["Cache-Control"] = "private, no-store"
            return response
        response = HttpResponse(status=204)
        response["Cache-Control"] = "private, no-store"
        return response

    # POST
    try:
        raw_token, row = create_token(request.user.pk)
    except TokenExistsError:
        return _response(
            {"errors": {"detail": "A token already exists."}, "code": "token_exists"},
            status=409,
        )
    except ScheduleChanged as exc:
        response = schedule_changed_response(exc)
        response["Cache-Control"] = "private, no-store"
        return response
    return _response(
        {"token": raw_token, "has_token": True, "created_at": row.created_at.isoformat()},
        status=201,
    )
