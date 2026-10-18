from django.conf import settings


def vite_dev_mode(request):
    return {
        "vite_dev_mode": settings.DEBUG,
        "frontend_release": settings.FRONTEND_RELEASE,
        "frontend_version": settings.INERTIA_VERSION,
    }
