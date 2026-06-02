import django
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, override_settings

# Ensure Django is set up before tests run
if not settings.configured:
    django.setup()

from schedules.models import Schedule  # noqa: E402  (must come after django.setup)


@pytest.fixture(scope="session", autouse=True)
def _force_test_safe_http_settings():
    """Force test-safe HTTP behavior regardless of the host shell's
    ``DEBUG`` env var.

    When a developer runs ``pytest`` with a production-shaped ``.env``
    (``DEBUG=0``), ``settings.py`` enables ``SECURE_SSL_REDIRECT=True``
    and the cookie-secure flags, which makes Django's test ``Client``
    receive a 301 redirect on every request before any view code runs.
    These overrides keep the test surface decoupled from the deploy-time
    env. Production-only HSTS is also disabled so test response headers
    stay predictable. Session-scoped + autouse so the overrides apply
    before the first request of the first test and stay in place for
    the entire suite.

    ``SecurityMiddleware`` reads ``SECURE_SSL_REDIRECT`` per request, so
    mutating ``settings`` here (rather than in a per-test ``override_
    settings`` context) is correct: the change takes effect on the next
    request and lasts for the session.
    """
    settings.SECURE_SSL_REDIRECT = False
    settings.SESSION_COOKIE_SECURE = False
    settings.CSRF_COOKIE_SECURE = False
    settings.SECURE_HSTS_SECONDS = 0
    yield


@pytest.fixture(scope="session", autouse=True)
def _pin_test_cache_backend():
    """Pin ``CACHES['default']`` to ``LocMemCache`` for the whole suite,
    independent of the host shell / CI ``.env``.

    Feature 0015 builds ``CACHES['default']`` from ``REDIS_URL`` at
    settings-import time (``settings.py`` calls ``load_dotenv``). A
    developer or CI runner whose ``.env`` defines ``REDIS_URL`` — exactly
    the var this feature introduces and documents in ``.env.example`` —
    would otherwise make the entire unit suite try to connect to a live
    Redis at import, turning every cache-touching test (``TestRateLimit``,
    the ``cache.get`` assertions in the chat/draft view tests, and the
    autouse ``_clear_cache``) into a connection-error failure with no
    Redis running.

    ``override_settings`` (not a raw ``settings.CACHES`` mutation) is
    required: ``ConnectionHandler`` caches the resolved config on first
    access, and ``caches.close_all()`` drops backend instances without
    invalidating that cached config — so ``caches['default']`` can still
    return the pre-pin backend. ``override_settings`` emits the
    ``setting_changed`` signal for ``CACHES``, which makes the handler
    re-read the config. Tests that genuinely need another backend (e.g.
    the Redis / FileBased cases in ``test_checks.py``) keep their own
    per-test ``override_settings(CACHES=...)``, which transparently
    shadows this session pin for their duration. Session-scoped + autouse
    so it wraps the first request of the first test.
    """
    with override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    ):
        yield


@pytest.fixture(autouse=True)
def _clear_cache():
    """The AI command endpoint uses the default cache for per-user rate
    limiting, and ``LocMemCache`` (pinned by ``_pin_test_cache_backend``)
    persists across tests in the same process. Clear before and after
    every test so rate-limit counters don't leak."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", password="testpass123")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.login(username="testuser", password="testpass123")
    return client


@pytest.fixture
def csrf_client():
    return Client(enforce_csrf_checks=True)


@pytest.fixture
def csrf_auth_client(user):
    client = Client(enforce_csrf_checks=True)
    client.login(username="testuser", password="testpass123")
    return client


@pytest.fixture
def schedule(user):
    return Schedule.objects.create(date="2026-04-07", user=user)
