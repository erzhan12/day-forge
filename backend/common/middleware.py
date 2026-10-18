"""Bind frontend requests to their session owner and application release."""

from django.http import JsonResponse
from inertia import share
from inertia.middleware import InertiaMiddleware


class ReleaseInertiaMiddleware(InertiaMiddleware):
    def is_stale(self, request):
        # inertia-django 1.2 also refreshes POSTs after executing the view.
        # Reopening a POST-only logout URL as GET produces a 405. Preserve
        # the redirect; the subsequent GET performs the version handshake.
        return request.method in {"GET", "HEAD"} and super().is_stale(request)


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


class FrontendVersionMiddleware:
    """Reject outdated clients before a view can write, including legacy tabs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from inertia import location

        version = settings.INERTIA_VERSION
        if version != "development":
            if request.headers.get("X-Inertia") and request.method in {"GET", "HEAD"}:
                if request.headers.get("X-Inertia-Version") != version:
                    return location(request.build_absolute_uri())
            if request.path.startswith("/api/"):
                supplied = request.headers.get("X-Frontend-Version")
                # Old releases do not send this header. Reads remain compatible;
                # writes without an identity must never reach the new API.
                if supplied != version and (
                    supplied is not None
                    or request.method
                    not in {
                        "GET",
                        "HEAD",
                        "OPTIONS",
                    }
                ):
                    response = JsonResponse(
                        {
                            "code": "frontend_outdated",
                            "errors": {"detail": "The app has been updated. Reload to continue."},
                        },
                        status=409,
                    )
                    response["Cache-Control"] = "no-store"
                    return response
        return self.get_response(request)
