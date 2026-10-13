"""Contracts shared by the four provider integrations."""

import asyncio
import threading
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from calendar_sync import cache as caldav_cache
from calendar_sync import crypto as caldav_crypto
from calendar_sync import service as caldav_service
from calendar_sync.models import CalDAVAccount
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from gcal_sync import cache as google_cache
from gcal_sync import crypto as google_crypto
from habitica_sync import cache as habitica_cache
from habitica_sync import crypto as habitica_crypto
from habitica_sync import service as habitica_service
from habitica_sync.models import HabiticaAccount
from todoist_sync import cache as todoist_cache
from todoist_sync import crypto as todoist_crypto
from todoist_sync import service as todoist_service
from todoist_sync.models import TodoistAccount


def test_google_cache_io_runs_outside_the_event_loop(monkeypatch):
    event_loop_thread = threading.get_ident()
    calls = []
    account = SimpleNamespace(user_id=2, id=3, updated_at=datetime(2026, 10, 10, tzinfo=UTC))
    rows = [{"id": "event"}]

    def read(key):
        calls.append(("read", threading.get_ident()))
        return rows

    def write(key, value, timeout):
        calls.append(("write", threading.get_ident()))
        assert value == rows

    monkeypatch.setattr(google_cache.cache, "get", read)
    monkeypatch.setattr(google_cache.cache, "set", write)

    async def exercise():
        assert await google_cache.get_cached_events(account, date(2026, 10, 10)) == rows
        await google_cache.set_cached_events(account, date(2026, 10, 10), rows)

    asyncio.run(exercise())
    assert [operation for operation, _ in calls] == ["read", "write"]
    assert all(thread_id != event_loop_thread for _, thread_id in calls)


@pytest.mark.parametrize(
    ("setting_name", "encrypt", "decrypt"),
    [
        ("CALDAV_ENCRYPTION_KEY", caldav_crypto.encrypt_password, caldav_crypto.decrypt_password),
        ("GOOGLE_OAUTH_TOKEN_KEY", google_crypto.encrypt_token, google_crypto.decrypt_token),
        ("HABITICA_ENCRYPTION_KEY", habitica_crypto.encrypt_token, habitica_crypto.decrypt_token),
        ("TODOIST_ENCRYPTION_KEY", todoist_crypto.encrypt_token, todoist_crypto.decrypt_token),
    ],
)
def test_existing_fernet_ciphertext_and_key_failures(setting_name, encrypt, decrypt):
    old_key = Fernet.generate_key()
    plaintext = "credential-秘密"
    old_ciphertext = Fernet(old_key).encrypt(plaintext.encode())
    with override_settings(**{setting_name: old_key.decode()}):
        assert decrypt(old_ciphertext) == plaintext
        assert decrypt(memoryview(old_ciphertext)) == plaintext
        assert Fernet(old_key).decrypt(encrypt(plaintext)).decode() == plaintext
        with pytest.raises(ImproperlyConfigured) as invalid_utf8:
            decrypt(Fernet(old_key).encrypt(b"\xffprivate-value"))
        assert "private-value" not in str(invalid_utf8.value)

    with override_settings(**{setting_name: Fernet.generate_key().decode()}):
        with pytest.raises(ImproperlyConfigured) as exc:
            decrypt(old_ciphertext)
        assert setting_name in str(exc.value)
        assert plaintext not in str(exc.value)
        assert old_ciphertext.decode() not in str(exc.value)

    for key in ("", "invalid-key"):
        with override_settings(**{setting_name: key}):
            with pytest.raises(ImproperlyConfigured) as exc:
                encrypt(plaintext)
            assert plaintext not in str(exc.value)


def test_provider_keys_remain_independent():
    keys = {
        name: Fernet.generate_key().decode()
        for name in (
            "CALDAV_ENCRYPTION_KEY",
            "GOOGLE_OAUTH_TOKEN_KEY",
            "HABITICA_ENCRYPTION_KEY",
            "TODOIST_ENCRYPTION_KEY",
        )
    }
    with override_settings(**keys):
        ciphertext = caldav_crypto.encrypt_password("private-value")
        for decrypt in (
            google_crypto.decrypt_token,
            habitica_crypto.decrypt_token,
            todoist_crypto.decrypt_token,
        ):
            with pytest.raises(ImproperlyConfigured):
                decrypt(ciphertext)


def test_cache_keys_preserve_provider_identity_and_filter_scope():
    account = SimpleNamespace(
        user_id=7,
        id=11,
        updated_at=datetime(2026, 5, 7, 12, 13, 14, 123456, UTC),
    )
    day = date(2026, 5, 7)
    assert caldav_cache.events_cache_key(account, day, "Asia/Qatar") == (
        "caldav_events:v2:7:2026-05-07T12:13:14.123456+00:00:2026-05-07:Asia/Qatar"
    )
    assert google_cache.events_cache_key(account, day, "Asia/Qatar") == (
        "gcal_events:v2:7:11:2026-05-07T12:13:14.123456+00:00:2026-05-07:Asia/Qatar"
    )
    for cache_module, namespace in (
        (habitica_cache, "habitica_tasks"),
        (todoist_cache, "todoist_tasks"),
    ):
        exact = cache_module.tasks_cache_key(
            account, day, time_zone="Asia/Qatar", filter_scope="exact"
        )
        overdue = cache_module.tasks_cache_key(
            account, day, time_zone="Asia/Qatar", filter_scope="with_overdue"
        )
        assert exact == (
            f"{namespace}:7:2026-05-07T12:13:14.123456+00:00:Asia/Qatar:2026-05-07:exact"
        )
        assert exact != overdue


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("path", "service_path", "error_type", "payload"),
    [
        (
            "/api/calendar/account/",
            "calendar_sync.service.verify_credentials",
            caldav_service.CalDAVAuthError,
            {"apple_id": "alice@example.com", "password": "incorrect"},
        ),
        (
            "/api/todoist/account/",
            "todoist_sync.service.verify_credentials",
            todoist_service.TodoistAuthError,
            {"token": "incorrect"},
        ),
        (
            "/api/habitica/account/",
            "habitica_sync.service.verify_credentials",
            habitica_service.HabiticaAuthError,
            {"api_user_id": "alice", "api_token": "incorrect"},
        ),
    ],
)
def test_failed_account_verification_is_not_session_expiry(
    client,
    django_user_model,
    path,
    service_path,
    error_type,
    payload,
):
    user = django_user_model.objects.create_user(username="integration-user")
    client.force_login(user)
    with patch(service_path, side_effect=error_type("private-value")):
        response = client.post(path, data=payload, content_type="application/json")
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "integration_credentials_error"
    assert body["meta"] == {
        "account_state": "disconnected",
        "resource_state": "credentials_error",
    }
    assert "private-value" not in str(body)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/api/calendar/events/2026-05-07/",
        "/api/calendar/google/events/2026-05-07/",
        "/api/todoist/tasks/2026-05-07/",
        "/api/habitica/tasks/2026-05-07/",
    ],
)
def test_missing_account_is_explicit_resource_state(client, django_user_model, path):
    user = django_user_model.objects.create_user(username="integration-user")
    client.force_login(user)
    response = client.get(path)
    assert response.status_code == 503
    assert response.json()["code"] == "integration_account_missing"
    assert response.json()["meta"] == {
        "account_state": "disconnected",
        "resource_state": "unavailable",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("provider", ["caldav", "todoist", "habitica"])
@pytest.mark.parametrize(
    ("error_kind", "status", "resource_state", "code"),
    [
        ("auth", 401, "credentials_error", "integration_credentials_error"),
        ("provider", 502, "provider_error", "integration_provider_error"),
        ("timeout", 504, "unavailable", "integration_unavailable"),
    ],
)
def test_resource_failure_preserves_account_state(
    client,
    django_user_model,
    settings,
    provider,
    error_kind,
    status,
    resource_state,
    code,
):
    user = django_user_model.objects.create_user(username="integration-user")
    client.force_login(user)
    key = Fernet.generate_key().decode()
    settings.CALDAV_ENCRYPTION_KEY = key
    settings.TODOIST_ENCRYPTION_KEY = key
    settings.HABITICA_ENCRYPTION_KEY = key

    if provider == "caldav":
        account = CalDAVAccount(user=user, apple_id="a@example.com", base_url="https://example.com")
        account.set_password("secret")
        route = "/api/calendar/events/2026-05-07/"
        target = "calendar_sync.service.fetch_events_for_date"
        errors = {
            "auth": caldav_service.CalDAVAuthError,
            "provider": caldav_service.CalDAVProviderError,
            "timeout": caldav_service.CalDAVTimeoutError,
        }
    elif provider == "todoist":
        account = TodoistAccount(user=user)
        account.set_token("secret")
        route = "/api/todoist/tasks/2026-05-07/"
        target = "todoist_sync.service.fetch_tasks_for_date"
        errors = {
            "auth": todoist_service.TodoistAuthError,
            "provider": todoist_service.TodoistProviderError,
            "timeout": todoist_service.TodoistTimeoutError,
        }
    else:
        account = HabiticaAccount(user=user, api_user_id="habitica-user")
        account.set_token("secret")
        route = "/api/habitica/tasks/2026-05-07/"
        target = "habitica_sync.service.fetch_tasks_for_date"
        errors = {
            "auth": habitica_service.HabiticaAuthError,
            "provider": habitica_service.HabiticaProviderError,
            "timeout": habitica_service.HabiticaTimeoutError,
        }
    account.save()
    with patch(target, side_effect=errors[error_kind]("private-value")):
        response = client.get(route)
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["meta"] == {
        "account_state": "connected",
        "resource_state": resource_state,
    }
    assert "private-value" not in str(body)
