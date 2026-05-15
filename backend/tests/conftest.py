import django
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client

# Ensure Django is set up before tests run
if not settings.configured:
    django.setup()

# Force test-safe HTTP behavior regardless of the host shell's ``DEBUG``
# env var. When a developer runs ``pytest`` with a production-shaped
# ``.env`` (``DEBUG=0``), ``settings.py`` enables
# ``SECURE_SSL_REDIRECT=True`` and the cookie-secure flags, which makes
# Django's test ``Client`` receive a 301 redirect on every request
# before any view code runs. These overrides keep the test surface
# decoupled from the deploy-time env. (Production-only HSTS settings
# are also disabled so test response headers stay predictable.)
settings.SECURE_SSL_REDIRECT = False
settings.SESSION_COOKIE_SECURE = False
settings.CSRF_COOKIE_SECURE = False
settings.SECURE_HSTS_SECONDS = 0

from schedules.models import Schedule  # noqa: E402  (must come after django.setup)


@pytest.fixture(autouse=True)
def _clear_cache():
    """The AI command endpoint uses the default cache for per-user rate
    limiting, and LocMemCache persists across tests in the same process.
    Clear before and after every test so rate-limit counters don't leak."""
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
