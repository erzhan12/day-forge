import datetime
import json
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.test import Client
from habitica_sync import service
from habitica_sync.models import HabiticaAccount
from habitica_sync.schemas import NormalizedHabiticaTask

FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _habitica_settings(settings):
    settings.HABITICA_ENCRYPTION_KEY = FERNET_KEY
    settings.HABITICA_CLIENT_ID = "maintainer-user"
    settings.HABITICA_BASE_URL = "https://habitica.test/api/v3"
    settings.HABITICA_REQUEST_TIMEOUT = 5
    settings.HABITICA_CACHE_TTL_SECONDS = 300


@pytest.fixture
def user(db):
    return User.objects.create_user(username="habitica-view-user", password="x")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def account(user):
    acc = HabiticaAccount(user=user, api_user_id="habitica-id")
    acc.set_token("habitica-token")
    acc.last_verified_at = datetime.datetime(2026, 7, 22, 9, tzinfo=datetime.UTC)
    acc.save()
    return acc


def _assert_envelope(resp):
    body = resp.json()
    assert "errors" in body
    assert isinstance(body["errors"]["detail"], str)
    assert body["errors"]["detail"]


def test_account_status_includes_user_id_but_no_token(auth_client, account):
    resp = auth_client.get("/api/habitica/account/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["connected"] is True
    assert body["api_user_id"] == "habitica-id"
    assert not any("token" in key.lower() for key in body)


def test_account_status_disconnected_shape(auth_client):
    resp = auth_client.get("/api/habitica/account/")
    assert resp.status_code == 200
    assert resp.json() == {
        "connected": False,
        "last_verified_at": None,
        "api_user_id": None,
    }


def test_post_verifies_and_persists_encrypted_token(auth_client, user):
    with patch("habitica_sync.service.verify_credentials") as verify:
        verify.return_value = None
        resp = auth_client.post(
            "/api/habitica/account/",
            data={"api_user_id": "uid", "api_token": "secret-token"},
            content_type="application/json",
        )

    assert resp.status_code == 200
    verify.assert_called_once_with("uid", "secret-token")
    acc = HabiticaAccount.objects.get(user=user)
    assert acc.api_user_id == "uid"
    assert bytes(acc.api_token_encrypted) != b"secret-token"
    assert acc.get_token() == "secret-token"
    assert resp.json()["api_user_id"] == "uid"


def test_post_validation_errors(auth_client):
    resp = auth_client.post(
        "/api/habitica/account/",
        data={"api_user_id": "", "api_token": ""},
        content_type="application/json",
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "api_user_id" in body["errors"]
    assert "api_token" in body["errors"]


def test_post_auth_failure_maps_to_401(auth_client):
    with patch("habitica_sync.service.verify_credentials") as verify:
        verify.side_effect = service.HabiticaAuthError("bad")
        resp = auth_client.post(
            "/api/habitica/account/",
            data={"api_user_id": "uid", "api_token": "bad"},
            content_type="application/json",
        )
    assert resp.status_code == 401
    _assert_envelope(resp)


def test_tasks_503_without_account(auth_client):
    resp = auth_client.get("/api/habitica/tasks/2026-07-22/")
    assert resp.status_code == 503
    _assert_envelope(resp)


def test_tasks_cache_hit_miss_and_refresh(auth_client, account):
    task = NormalizedHabiticaTask(
        id="a",
        title="A",
        type="todo",
        due_date="2026-07-22",
        completed=False,
    )
    with patch("habitica_sync.service.fetch_tasks_for_date") as fetch:
        fetch.return_value = [task]
        first = auth_client.get("/api/habitica/tasks/2026-07-22/")
        second = auth_client.get("/api/habitica/tasks/2026-07-22/")
        refresh = auth_client.get("/api/habitica/tasks/2026-07-22/?refresh=1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert refresh.status_code == 200
    assert fetch.call_count == 2
    assert first.json()["tasks"] == [
        {
            "id": "a",
            "title": "A",
            "type": "todo",
            "due_date": "2026-07-22",
            "completed": False,
        }
    ]


def test_complete_invalidates_cache(auth_client, account):
    before = account.updated_at
    with patch("habitica_sync.service.complete_task") as complete:
        complete.return_value = None
        resp = auth_client.post("/api/habitica/tasks/task-id/complete/")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    complete.assert_called_once()
    account.refresh_from_db()
    assert account.updated_at > before


def test_complete_error_mapping(auth_client, account):
    with patch("habitica_sync.service.complete_task") as complete:
        complete.side_effect = service.HabiticaTimeoutError("slow")
        resp = auth_client.post("/api/habitica/tasks/task-id/complete/")
    assert resp.status_code == 504
    _assert_envelope(resp)


def test_account_post_maps_improperly_configured_to_500(auth_client, user):
    """A bad Fernet key surfaces on connect BEFORE it can surface anywhere else.

    ``set_token`` encrypts, so this is the first path a misconfigured key
    reaches — exactly what the habitica_sync.E001 hint describes. It must
    return the same config envelope as the tasks/complete views rather than a
    bare 500.
    """
    with patch("habitica_sync.service.verify_credentials"):
        with patch.object(
            HabiticaAccount, "set_token", side_effect=ImproperlyConfigured("bad key")
        ):
            resp = auth_client.post(
                "/api/habitica/account/",
                json.dumps({"api_user_id": "u", "api_token": "t"}),
                content_type="application/json",
            )

    assert resp.status_code == 500
    _assert_envelope(resp)
    # The transaction must roll back — no half-written row.
    assert not HabiticaAccount.objects.filter(user=user).exists()


def test_account_post_rejects_oversized_body(auth_client, user):
    """The body cap short-circuits before JSON parsing or any provider call.

    Mirrors ``test_analytics_views.test_oversized_body_returns_413``.
    """
    big = "x" * 200_000
    with patch("habitica_sync.service.verify_credentials") as verify:
        resp = auth_client.post(
            "/api/habitica/account/",
            json.dumps({"api_user_id": "u", "api_token": big}),
            content_type="application/json",
        )

    assert resp.status_code == 413
    verify.assert_not_called()
    assert not HabiticaAccount.objects.filter(user=user).exists()


def test_tasks_rejects_malformed_date(auth_client, account):
    """A bad date must 400 BEFORE any provider call is attempted."""
    with patch("habitica_sync.service.fetch_tasks_for_date") as fetch:
        resp = auth_client.get("/api/habitica/tasks/not-a-date/")

    assert resp.status_code == 400
    _assert_envelope(resp)
    fetch.assert_not_called()


def test_tasks_maps_improperly_configured_to_500(auth_client, account):
    """A rotated/broken Fernet key surfaces as a config-shaped 500.

    This is the documented key-rotation recovery path in
    `.claude/rules/project.md`; without a test the handler is dead code the
    first time an operator actually rotates the key.
    """
    with patch("habitica_sync.service.fetch_tasks_for_date") as fetch:
        fetch.side_effect = ImproperlyConfigured("bad key")
        resp = auth_client.get("/api/habitica/tasks/2026-07-22/")

    assert resp.status_code == 500
    _assert_envelope(resp)


def test_complete_maps_improperly_configured_to_500(auth_client, account):
    with patch("habitica_sync.service.complete_task") as complete:
        complete.side_effect = ImproperlyConfigured("bad key")
        resp = auth_client.post("/api/habitica/tasks/task-id/complete/")

    assert resp.status_code == 500
    _assert_envelope(resp)


def test_tasks_maps_provider_error_to_502(auth_client, account):
    with patch("habitica_sync.service.fetch_tasks_for_date") as fetch:
        fetch.side_effect = service.HabiticaProviderError("upstream broke")
        resp = auth_client.get("/api/habitica/tasks/2026-07-22/")

    assert resp.status_code == 502
    _assert_envelope(resp)


def test_invalidate_tasks_does_not_clobber_concurrent_token_update(account):
    """A stale in-memory account from an in-flight complete must not revert a
    concurrent token rotation when bumping the cache version.

    This is what forces the column-scoped ``filter(pk=...).update(...)`` in
    ``cache.invalidate_tasks``. A plain ``account.save()`` would write every
    field from the stale instance and undo the rotation — and the
    ``updated_at > before`` assertion above would still pass, so only this
    test discriminates the two implementations.
    """
    from habitica_sync import cache as habitica_cache

    stale_row = HabiticaAccount.objects.get(pk=account.pk)
    original_token = stale_row.get_token()

    fresh = HabiticaAccount.objects.get(pk=account.pk)
    fresh.set_token("new-token-after-reconnect")
    fresh.save()

    habitica_cache.invalidate_tasks(stale_row)

    reloaded = HabiticaAccount.objects.get(pk=account.pk)
    assert reloaded.get_token() == "new-token-after-reconnect"
    assert reloaded.get_token() != original_token
    assert reloaded.updated_at >= fresh.updated_at


def test_invalidate_tasks_does_not_resurrect_deleted_account(account):
    """A stale in-memory account must not be re-inserted after DELETE."""
    from habitica_sync import cache as habitica_cache

    stale_row = HabiticaAccount.objects.get(pk=account.pk)
    pk = stale_row.pk
    HabiticaAccount.objects.filter(pk=pk).delete()

    habitica_cache.invalidate_tasks(stale_row)

    assert not HabiticaAccount.objects.filter(pk=pk).exists()
