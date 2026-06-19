"""Endpoint tests for ``todoist_sync.views``.

Mirrors ``test_calendar_sync_views.py`` one-for-one: the four method
handlers plus envelope contract, cache hit / invalidation, 503 on missing
account, and per-error-status envelope shape.

Differences from CalDAV: a single ``token`` secret (no apple_id/base_url),
an HTTP REST client (``requests``) mocked at the service layer instead of a
DAV library, and a ``today | overdue`` filter whose branch depends on the
project-local "today" — so the today-vs-exact-date test pins
``timezone.localdate`` on a frozen value.
"""

import datetime
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.test import Client
from todoist_sync import service
from todoist_sync.models import TodoistAccount

FERNET_KEY = Fernet.generate_key().decode()


def _fake_response(results, next_cursor=None, status_code=200):
    """A stand-in ``requests.Response`` for the cursor-paginated filter
    endpoint — ``{results, next_cursor}`` (NOT a bare array)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {"results": results, "next_cursor": next_cursor}
    return resp


# One full-day Todoist task: raw ``content`` → wire ``title``; priority 4 → P1.
RAW_TASK = {
    "id": "1001",
    "content": "Ship the panel",
    "priority": 4,
    "due": {"date": "2026-05-07", "is_recurring": False, "string": "May 7"},
}


@pytest.fixture(autouse=True)
def _todoist_settings(settings):
    settings.TODOIST_ENCRYPTION_KEY = FERNET_KEY
    settings.TODOIST_BASE_URL = "https://api.todoist.com/api/v1"
    settings.TODOIST_REQUEST_TIMEOUT = 5
    settings.TODOIST_CACHE_TTL_SECONDS = 300


@pytest.fixture
def user(db):
    return User.objects.create_user(username="todo-user", password="testpass123")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.login(username="todo-user", password="testpass123")
    return client


@pytest.fixture
def account(user):
    acc = TodoistAccount(user=user)
    acc.set_token("0123456789abcdef0123456789abcdef01234567")
    acc.last_verified_at = datetime.datetime(2026, 5, 1, 9, 0, tzinfo=datetime.UTC)
    acc.save()
    return acc


def _assert_envelope(resp):
    body = resp.json()
    assert "errors" in body, f"missing errors envelope: {body!r}"
    assert "detail" in body["errors"], f"missing errors.detail: {body!r}"
    assert isinstance(body["errors"]["detail"], str)
    assert body["errors"]["detail"]


# ---- GET /api/todoist/account/ ------------------------------------------


class TestAccountGet:
    def test_returns_disconnected_status(self, auth_client):
        resp = auth_client.get("/api/todoist/account/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is False
        assert body["last_verified_at"] is None
        # Status payload never carries a token field of any shape.
        assert not any("token" in k.lower() for k in body.keys())

    def test_returns_connected_status_when_account_present(self, auth_client, account):
        resp = auth_client.get("/api/todoist/account/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["last_verified_at"] is not None
        # Never returns a token-shaped field.
        assert not any("token" in k.lower() for k in body.keys())


# ---- POST /api/todoist/account/ -----------------------------------------


class TestAccountPost:
    def test_post_persists_encrypted_password(self, auth_client, user):
        """POST encrypts + round-trips — ``token_encrypted`` Fernet-decrypts
        back to the original token (analog of CalDAV's
        ``test_post_persists_encrypted_password``)."""
        with patch("todoist_sync.service.verify_credentials") as verify:
            verify.return_value = None
            resp = auth_client.post(
                "/api/todoist/account/",
                data={"token": "secret-abc"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        acc = TodoistAccount.objects.get(user=user)
        # token_encrypted must NOT be the plaintext bytes.
        assert bytes(acc.token_encrypted) != b"secret-abc"
        # Round-trip via Fernet decrypt yields the original.
        assert acc.get_token() == "secret-abc"

    def test_post_invalid_credentials_does_not_persist(self, auth_client, user):
        with patch("todoist_sync.service.verify_credentials") as verify:
            verify.side_effect = service.TodoistAuthError("nope")
            resp = auth_client.post(
                "/api/todoist/account/",
                data={"token": "bad"},
                content_type="application/json",
            )
        assert resp.status_code == 401
        _assert_envelope(resp)
        assert not TodoistAccount.objects.filter(user=user).exists()

    def test_post_missing_token_returns_400_envelope(self, auth_client, user):
        resp = auth_client.post(
            "/api/todoist/account/",
            data={},
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "errors" in body
        assert "token" in body["errors"]
        assert not TodoistAccount.objects.filter(user=user).exists()

    def test_post_empty_token_returns_400_per_field(self, auth_client, user):
        resp = auth_client.post(
            "/api/todoist/account/",
            data={"token": "   "},
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "token" in body["errors"]
        assert not TodoistAccount.objects.filter(user=user).exists()

    def test_post_token_too_long_returns_400_per_field(self, auth_client, user):
        """Reject a > 128-char token before it hits Fernet/the HTTP client
        (Todoist tokens are ~40 hex chars; cap is 128)."""
        resp = auth_client.post(
            "/api/todoist/account/",
            data={"token": "x" * 200},
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "token" in body["errors"]
        assert "too long" in body["errors"]["token"]
        assert not TodoistAccount.objects.filter(user=user).exists()

    def test_post_invalid_json_returns_400_envelope(self, auth_client):
        resp = auth_client.post(
            "/api/todoist/account/",
            data="not json",
            content_type="application/json",
        )
        assert resp.status_code == 400
        _assert_envelope(resp)

    def test_post_timeout_returns_504_envelope(self, auth_client):
        with patch("todoist_sync.service.verify_credentials") as verify:
            verify.side_effect = service.TodoistTimeoutError("slow")
            resp = auth_client.post(
                "/api/todoist/account/",
                data={"token": "x"},
                content_type="application/json",
            )
        assert resp.status_code == 504
        _assert_envelope(resp)

    def test_post_provider_failure_returns_502_envelope(self, auth_client):
        with patch("todoist_sync.service.verify_credentials") as verify:
            verify.side_effect = service.TodoistProviderError("rest broke")
            resp = auth_client.post(
                "/api/todoist/account/",
                data={"token": "x"},
                content_type="application/json",
            )
        assert resp.status_code == 502
        _assert_envelope(resp)


# ---- DELETE /api/todoist/account/ ---------------------------------------


class TestAccountDelete:
    def test_delete_removes_row(self, auth_client, user, account):
        assert TodoistAccount.objects.filter(user=user).exists()
        resp = auth_client.delete("/api/todoist/account/")
        assert resp.status_code == 200
        assert resp.json()["connected"] is False
        assert not TodoistAccount.objects.filter(user=user).exists()

    def test_delete_is_idempotent(self, auth_client, user):
        resp = auth_client.delete("/api/todoist/account/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is False
        assert body["last_verified_at"] is None


# ---- GET /api/todoist/tasks/<date>/ -------------------------------------


class TestTasksEndpoint:
    def test_503_when_no_account(self, auth_client):
        resp = auth_client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code == 503
        body = resp.json()
        assert body["errors"]["detail"] == "No Todoist account configured"

    def test_400_on_invalid_date(self, auth_client, account):
        resp = auth_client.get("/api/todoist/tasks/not-a-date/")
        assert resp.status_code == 400
        _assert_envelope(resp)

    def test_fetch_success(self, auth_client, account):
        with patch("todoist_sync.service.requests.get") as get:
            get.return_value = _fake_response([RAW_TASK])
            resp = auth_client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code == 200
        body = resp.json()
        assert "tasks" in body
        assert len(body["tasks"]) == 1
        task = body["tasks"][0]
        # Wire field is ``title`` (never ``content``).
        assert task["title"] == "Ship the panel"
        assert "content" not in task
        # Priority mapping: raw 4 → P1 (highest).
        assert task["priority"] == 4
        assert task["ui_priority"] == "P1"
        assert task["due_date"] == "2026-05-07"
        assert set(task.keys()) == {
            "id",
            "title",
            "priority",
            "ui_priority",
            "due_date",
        }

    def test_cache_hit_short_circuits_second_call(self, auth_client, account):
        with patch("todoist_sync.service.requests.get") as get:
            get.return_value = _fake_response([RAW_TASK])

            r1 = auth_client.get("/api/todoist/tasks/2026-05-07/")
            assert r1.status_code == 200
            first_calls = get.call_count

            r2 = auth_client.get("/api/todoist/tasks/2026-05-07/")
            assert r2.status_code == 200
            # Cache hit must not issue a second provider call.
            assert get.call_count == first_calls
            assert r1.json() == r2.json()

    def test_exact_and_overdue_filters_use_separate_cache_entries(
        self, auth_client, account
    ):
        """A bare-date read must not poison the overdue-carryover cache."""
        frozen_today = datetime.date(2026, 5, 8)
        exact_task = {**RAW_TASK, "id": "exact", "content": "Exact only"}
        overdue_task = {**RAW_TASK, "id": "overdue", "content": "With overdue"}
        with patch(
            "todoist_sync.service.django_tz.localdate",
            return_value=frozen_today,
        ), patch("todoist_sync.service.requests.get") as get:
            get.side_effect = [
                _fake_response([exact_task]),
                _fake_response([exact_task, overdue_task]),
            ]
            r1 = auth_client.get("/api/todoist/tasks/2026-05-09/")
            assert r1.status_code == 200
            assert len(r1.json()["tasks"]) == 1

            r2 = auth_client.get("/api/todoist/tasks/2026-05-09/?carry_overdue=1")
            assert r2.status_code == 200
            assert len(r2.json()["tasks"]) == 2
            assert get.call_count == 2

    def test_auth_error_returns_401_envelope(self, auth_client, account):
        with patch(
            "todoist_sync.service.fetch_tasks_for_date",
            side_effect=service.TodoistAuthError("nope"),
        ):
            resp = auth_client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code == 401
        _assert_envelope(resp)

    def test_timeout_returns_504_envelope(self, auth_client, account):
        with patch(
            "todoist_sync.service.fetch_tasks_for_date",
            side_effect=service.TodoistTimeoutError("slow"),
        ):
            resp = auth_client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code == 504
        _assert_envelope(resp)

    def test_provider_failure_returns_502_envelope(self, auth_client, account):
        with patch(
            "todoist_sync.service.fetch_tasks_for_date",
            side_effect=service.TodoistProviderError("rest broke"),
        ):
            resp = auth_client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code == 502
        _assert_envelope(resp)

    def test_decryption_misconfig_returns_500_with_config_message(self, auth_client, account):
        """ImproperlyConfigured (e.g. TODOIST_ENCRYPTION_KEY rotated)
        must surface as a 500 with a config-shaped message — not as a
        502 "provider failure" that would mislead ops about Todoist's
        state (mirror of CalDAV's analog)."""
        from django.core.exceptions import ImproperlyConfigured
        with patch(
            "todoist_sync.service.fetch_tasks_for_date",
            side_effect=ImproperlyConfigured("key rotated"),
        ):
            resp = auth_client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code == 500
        body = resp.json()
        assert "misconfigured" in body["errors"]["detail"].lower()

    def test_today_uses_date_overdue_filter(self, auth_client, account):
        """On a frozen clock, ``selected_date == today`` → the generated
        Todoist ``query`` is ``"<YYYY-MM-DD> | overdue"``. No CalDAV analog —
        the filter string depends on "today", so we pin ``timezone.localdate``.
        """
        frozen_today = datetime.date(2026, 5, 7)
        with patch(
            "todoist_sync.service.django_tz.localdate",
            return_value=frozen_today,
        ), patch("todoist_sync.service.requests.get") as get:
            get.return_value = _fake_response([RAW_TASK])
            resp = auth_client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code == 200
        _, kwargs = get.call_args
        assert kwargs["params"]["query"] == "2026-05-07 | overdue"

    def test_carry_overdue_query_param(self, auth_client, account):
        """``?carry_overdue=1`` requests overdue carryover when the schedule
        date is browser-local today but not project-local today."""
        frozen_today = datetime.date(2026, 5, 7)
        with patch(
            "todoist_sync.service.django_tz.localdate",
            return_value=frozen_today,
        ), patch("todoist_sync.service.requests.get") as get:
            get.return_value = _fake_response([RAW_TASK])
            resp = auth_client.get("/api/todoist/tasks/2026-05-08/?carry_overdue=1")
        assert resp.status_code == 200
        _, kwargs = get.call_args
        assert kwargs["params"]["query"] == "2026-05-08 | overdue"

    def test_other_date_uses_exact_date_filter(self, auth_client, account):
        """A past/future date (≠ today) → the bare literal-date token
        ``"<YYYY-MM-DD>"`` (due: semantics)."""
        frozen_today = datetime.date(2026, 5, 7)
        with patch(
            "todoist_sync.service.django_tz.localdate",
            return_value=frozen_today,
        ), patch("todoist_sync.service.requests.get") as get:
            get.return_value = _fake_response([RAW_TASK])
            resp = auth_client.get("/api/todoist/tasks/2026-05-09/")
        assert resp.status_code == 200
        _, kwargs = get.call_args
        assert kwargs["params"]["query"] == "2026-05-09"


# ---- Cache invalidation via versioned keys ------------------------------


class TestCacheInvalidation:
    def test_cache_invalidates_on_account_update(self, auth_client, user, account):
        with patch("todoist_sync.service.requests.get") as get:
            get.return_value = _fake_response([RAW_TASK])

            # Prime cache.
            auth_client.get("/api/todoist/tasks/2026-05-07/")
            first_calls = get.call_count

            # Rotate the token via POST — must bump updated_at via auto_now.
            with patch("todoist_sync.service.verify_credentials") as verify:
                verify.return_value = None
                resp = auth_client.post(
                    "/api/todoist/account/",
                    data={"token": "new-token"},
                    content_type="application/json",
                )
                assert resp.status_code == 200

            # Second tasks call for the same date must MISS the cache and
            # issue a fresh provider call.
            auth_client.get("/api/todoist/tasks/2026-05-07/")
            assert get.call_count > first_calls

    def test_cache_invalidates_on_account_delete(self, auth_client, user, account):
        with patch("todoist_sync.service.requests.get") as get:
            get.return_value = _fake_response([RAW_TASK])
            auth_client.get("/api/todoist/tasks/2026-05-07/")

        auth_client.delete("/api/todoist/account/")
        # After delete, the tasks endpoint returns 503 regardless of any
        # leftover cache entries (the read path can't resolve a key without
        # an account row).
        resp = auth_client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code == 503
        _assert_envelope(resp)


# ---- CSRF guard ----------------------------------------------------------


class TestCsrfGuard:
    """Confirm CSRF middleware is active on the mutating endpoints —
    regression-catches an accidental ``@csrf_exempt``."""

    def test_post_without_csrf_token_returns_403(self, db):
        User.objects.create_user(username="csrf-todo", password="x")
        client = Client(enforce_csrf_checks=True)
        client.login(username="csrf-todo", password="x")
        resp = client.post(
            "/api/todoist/account/",
            data='{"token": "x"}',
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_delete_without_csrf_token_returns_403(self, db):
        User.objects.create_user(username="csrf-todo2", password="x")
        client = Client(enforce_csrf_checks=True)
        client.login(username="csrf-todo2", password="x")
        resp = client.delete("/api/todoist/account/")
        assert resp.status_code == 403


# ---- Authentication guard -----------------------------------------------


class TestAuthGuard:
    def test_anonymous_account_get_redirects_to_login(self, db):
        client = Client()
        resp = client.get("/api/todoist/account/")
        assert resp.status_code in (302, 401, 403)

    def test_anonymous_tasks_redirects_to_login(self, db):
        client = Client()
        resp = client.get("/api/todoist/tasks/2026-05-07/")
        assert resp.status_code in (302, 401, 403)
