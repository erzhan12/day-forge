import django
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client

# Ensure Django is set up before tests run
if not settings.configured:
    django.setup()

from schedules.models import Schedule  # noqa: E402  (must come after django.setup)


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
