"""Expose the current session owner to page-scoped client state."""

from django.http import JsonResponse
from inertia import share


class InertiaIdentityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Session cookies are shared across tabs. An old page must not submit
        # its snapshot into a different account with a coincident revision.
        expected_user = request.headers.get("X-Schedule-User")
        if (
            expected_user is not None
            and request.path.startswith("/api/")
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and (not request.user.is_authenticated or expected_user != str(request.user.pk))
        ):
            return JsonResponse(
                {
                    "code": "session_invalid",
                    "errors": {"detail": "Session changed. Reload and sign in again."},
                },
                status=401,
            )
        share(
            request,
            auth_user_id=request.user.pk if request.user.is_authenticated else None,
        )
        return self.get_response(request)
