"""Endpoint tests for ``calendar_sync.views``.

Cover the four method handlers plus envelope contract, cache hit /
invalidation, 503 on missing account, and per-error-status envelope
shape (test #13 in the plan).
"""

import datetime
from unittest.mock import MagicMock, patch

import caldav
import pytest
from calendar_sync import service
from calendar_sync.models import CalDAVAccount
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.test import Client

FERNET_KEY = Fernet.generate_key().decode()

VEVENT_TIMED = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:timed-001@example.com
DTSTAMP:20260507T000000Z
DTSTART:20260507T140000Z
DTEND:20260507T150000Z
SUMMARY:Lunch
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture(autouse=True)
def _caldav_settings(settings):
    settings.CALDAV_ENCRYPTION_KEY = FERNET_KEY
    settings.CALDAV_REQUEST_TIMEOUT = 5
    settings.CALDAV_CACHE_TTL_SECONDS = 300
    settings.CALDAV_DEFAULT_BASE_URL = "https://caldav.icloud.com/"


@pytest.fixture
def user(db):
    return User.objects.create_user(username="cal-user", password="testpass123")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.login(username="cal-user", password="testpass123")
    return client


@pytest.fixture
def account(user):
    acc = CalDAVAccount(
        user=user, apple_id="alice@example.com",
        base_url="https://caldav.icloud.com/",
    )
    acc.set_password("hunter2")
    acc.last_verified_at = datetime.datetime(2026, 5, 1, 9, 0, tzinfo=datetime.UTC)
    acc.save()
    return acc


def _caldav_event(data):
    return caldav.Event(client=None, data=data)


def _fake_principal_with(events):
    cal = MagicMock()
    cal.name = "Personal"
    cal.date_search.return_value = events
    principal = MagicMock()
    principal.calendars.return_value = [cal]
    return principal


def _assert_envelope(resp):
    body = resp.json()
    assert "errors" in body, f"missing errors envelope: {body!r}"
    assert "detail" in body["errors"], f"missing errors.detail: {body!r}"
    assert isinstance(body["errors"]["detail"], str)
    assert body["errors"]["detail"]


# ---- GET /api/calendar/account/ -----------------------------------------


class TestAccountGet:
    def test_returns_disconnected_status_with_default_base_url(self, auth_client):
        resp = auth_client.get("/api/calendar/account/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is False
        assert body["apple_id"] is None
        assert body["base_url"] is None
        assert body["last_verified_at"] is None
        assert body["default_base_url"] == "https://caldav.icloud.com/"

    def test_returns_connected_status_when_account_present(self, auth_client, account):
        resp = auth_client.get("/api/calendar/account/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is True
        assert body["apple_id"] == "alice@example.com"
        assert body["base_url"] == "https://caldav.icloud.com/"
        assert body["last_verified_at"] is not None
        # Test #9: never returns a password-shaped field.
        assert not any("password" in k.lower() for k in body.keys())


# ---- POST /api/calendar/account/ ----------------------------------------


class TestAccountPost:
    def test_post_persists_encrypted_password(self, auth_client, user):
        with patch("calendar_sync.service.verify_credentials") as verify:
            verify.return_value = None
            resp = auth_client.post(
                "/api/calendar/account/",
                data={"apple_id": "alice@example.com", "password": "secret-abc"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        acc = CalDAVAccount.objects.get(user=user)
        # password_encrypted must NOT be the plaintext bytes.
        assert bytes(acc.password_encrypted) != b"secret-abc"
        # Round-trip via Fernet decrypt yields the original.
        assert acc.get_password() == "secret-abc"

    def test_post_invalid_credentials_does_not_persist(self, auth_client, user):
        with patch("calendar_sync.service.verify_credentials") as verify:
            verify.side_effect = service.CalDAVAuthError("nope")
            resp = auth_client.post(
                "/api/calendar/account/",
                data={"apple_id": "alice@example.com", "password": "bad"},
                content_type="application/json",
            )
        assert resp.status_code == 401
        _assert_envelope(resp)
        assert not CalDAVAccount.objects.filter(user=user).exists()

    def test_post_missing_fields_returns_400_envelope(self, auth_client):
        resp = auth_client.post(
            "/api/calendar/account/",
            data={"apple_id": "alice@example.com"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        _assert_envelope(resp)

    def test_post_malformed_apple_id_returns_400_per_field(self, auth_client, user):
        """Malformed email must surface as a per-field 400 — not as a
        provider-failure 502 after the DAVClient connects (review finding)."""
        resp = auth_client.post(
            "/api/calendar/account/",
            data={"apple_id": "not-an-email", "password": "x"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "errors" in body
        assert "apple_id" in body["errors"]
        assert not CalDAVAccount.objects.filter(user=user).exists()

    def test_post_malformed_base_url_returns_400_per_field(self, auth_client, user):
        resp = auth_client.post(
            "/api/calendar/account/",
            data={
                "apple_id": "alice@example.com",
                "password": "x",
                "base_url": "not a url",
            },
            content_type="application/json",
        )
        assert resp.status_code == 400
        body = resp.json()
        assert "errors" in body
        assert "base_url" in body["errors"]
        assert not CalDAVAccount.objects.filter(user=user).exists()

    def test_post_empty_base_url_falls_back_to_default(self, auth_client, user):
        """Empty/whitespace base_url is NOT a validation error — view
        substitutes settings.CALDAV_DEFAULT_BASE_URL."""
        with patch("calendar_sync.service.verify_credentials") as verify:
            verify.return_value = None
            resp = auth_client.post(
                "/api/calendar/account/",
                data={
                    "apple_id": "alice@example.com",
                    "password": "x",
                    "base_url": "",
                },
                content_type="application/json",
            )
        assert resp.status_code == 200
        acc = CalDAVAccount.objects.get(user=user)
        assert acc.base_url == "https://caldav.icloud.com/"

    def test_post_timeout_returns_504_envelope(self, auth_client):
        with patch("calendar_sync.service.verify_credentials") as verify:
            verify.side_effect = service.CalDAVTimeoutError("slow")
            resp = auth_client.post(
                "/api/calendar/account/",
                data={"apple_id": "a@b.com", "password": "x"},
                content_type="application/json",
            )
        assert resp.status_code == 504
        _assert_envelope(resp)

    def test_post_provider_failure_returns_502_envelope(self, auth_client):
        with patch("calendar_sync.service.verify_credentials") as verify:
            verify.side_effect = service.CalDAVProviderError("dav broke")
            resp = auth_client.post(
                "/api/calendar/account/",
                data={"apple_id": "a@b.com", "password": "x"},
                content_type="application/json",
            )
        assert resp.status_code == 502
        _assert_envelope(resp)


# ---- DELETE /api/calendar/account/ --------------------------------------


class TestAccountDelete:
    def test_delete_removes_row(self, auth_client, user, account):
        assert CalDAVAccount.objects.filter(user=user).exists()
        resp = auth_client.delete("/api/calendar/account/")
        assert resp.status_code == 200
        assert resp.json()["connected"] is False
        assert not CalDAVAccount.objects.filter(user=user).exists()

    def test_delete_is_idempotent(self, auth_client, user):
        resp = auth_client.delete("/api/calendar/account/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["connected"] is False
        assert body["default_base_url"] == "https://caldav.icloud.com/"


# ---- GET /api/calendar/events/<date>/ -----------------------------------


class TestEventsEndpoint:
    def test_503_when_no_account(self, auth_client):
        resp = auth_client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code == 503
        _assert_envelope(resp)

    def test_400_on_invalid_date(self, auth_client, account):
        resp = auth_client.get("/api/calendar/events/not-a-date/")
        assert resp.status_code == 400
        _assert_envelope(resp)

    def test_fetch_success(self, auth_client, account):
        with patch("calendar_sync.service.caldav.DAVClient") as cls:
            inst = MagicMock()
            cls.return_value = inst
            inst.principal.return_value = _fake_principal_with([_caldav_event(VEVENT_TIMED)])
            resp = auth_client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code == 200
        body = resp.json()
        assert "events" in body
        assert len(body["events"]) == 1
        ev = body["events"][0]
        assert ev["title"] == "Lunch"
        assert ev["calendar_name"] == "Personal"
        assert ev["all_day"] is False
        assert "external_uid" in ev

    def test_cache_hit_short_circuits_second_call(self, auth_client, account):
        with patch("calendar_sync.service.caldav.DAVClient") as cls:
            inst = MagicMock()
            cls.return_value = inst
            inst.principal.return_value = _fake_principal_with([_caldav_event(VEVENT_TIMED)])

            r1 = auth_client.get("/api/calendar/events/2026-05-07/")
            assert r1.status_code == 200
            first_calls = cls.call_count

            r2 = auth_client.get("/api/calendar/events/2026-05-07/")
            assert r2.status_code == 200
            # Cache hit must not open a second DAV client.
            assert cls.call_count == first_calls
            assert r1.json() == r2.json()

    def test_auth_error_returns_401_envelope(self, auth_client, account):
        with patch(
            "calendar_sync.service.fetch_events_for_date",
            side_effect=service.CalDAVAuthError("nope"),
        ):
            resp = auth_client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code == 401
        _assert_envelope(resp)

    def test_timeout_returns_504_envelope(self, auth_client, account):
        with patch(
            "calendar_sync.service.fetch_events_for_date",
            side_effect=service.CalDAVTimeoutError("slow"),
        ):
            resp = auth_client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code == 504
        _assert_envelope(resp)

    def test_provider_failure_returns_502_envelope(self, auth_client, account):
        with patch(
            "calendar_sync.service.fetch_events_for_date",
            side_effect=service.CalDAVProviderError("dav broke"),
        ):
            resp = auth_client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code == 502
        _assert_envelope(resp)

    def test_decryption_misconfig_returns_500_with_config_message(self, auth_client, account):
        """ImproperlyConfigured (e.g. CALDAV_ENCRYPTION_KEY rotated)
        must surface as a 500 with a config-shaped message — not as a
        502 "provider failure" that would mislead ops about iCloud's
        state (review finding)."""
        from django.core.exceptions import ImproperlyConfigured
        with patch(
            "calendar_sync.service.fetch_events_for_date",
            side_effect=ImproperlyConfigured("key rotated"),
        ):
            resp = auth_client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code == 500
        body = resp.json()
        assert "misconfigured" in body["errors"]["detail"].lower()

    def test_per_calendar_dav_error_returns_502_envelope(self, auth_client, account):
        """End-to-end view test for the date_search-level provider error
        (review finding). The single-calendar case must NOT yield a
        falsely-empty 200 response."""
        from caldav.lib.error import DAVError as _DAVError
        with patch("calendar_sync.service.caldav.DAVClient") as cls:
            inst = MagicMock()
            cls.return_value = inst
            cal = MagicMock()
            cal.name = "Personal"
            cal.date_search.side_effect = _DAVError("dav broke")
            principal = MagicMock()
            principal.calendars.return_value = [cal]
            inst.principal.return_value = principal

            resp = auth_client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code == 502
        _assert_envelope(resp)


# ---- Cache invalidation via versioned keys ------------------------------


class TestCacheInvalidation:
    def test_cache_invalidates_on_account_update(self, auth_client, user, account):
        with patch("calendar_sync.service.caldav.DAVClient") as cls:
            inst = MagicMock()
            cls.return_value = inst
            inst.principal.return_value = _fake_principal_with([_caldav_event(VEVENT_TIMED)])

            # Prime cache
            auth_client.get("/api/calendar/events/2026-05-07/")
            first_calls = cls.call_count

            # Rotate credentials via POST — must bump updated_at via auto_now.
            with patch("calendar_sync.service.verify_credentials") as verify:
                verify.return_value = None
                resp = auth_client.post(
                    "/api/calendar/account/",
                    data={"apple_id": "alice@example.com", "password": "new-pass"},
                    content_type="application/json",
                )
                assert resp.status_code == 200

            # Second events call for the same date must MISS the cache and
            # open a fresh DAV client.
            auth_client.get("/api/calendar/events/2026-05-07/")
            assert cls.call_count > first_calls

    def test_cache_invalidates_on_account_delete(self, auth_client, user, account):
        with patch("calendar_sync.service.caldav.DAVClient") as cls:
            inst = MagicMock()
            cls.return_value = inst
            inst.principal.return_value = _fake_principal_with([_caldav_event(VEVENT_TIMED)])
            auth_client.get("/api/calendar/events/2026-05-07/")

        auth_client.delete("/api/calendar/account/")
        # After delete, events endpoint returns 503 regardless of any
        # leftover cache entries (the read path can't resolve a key
        # without an account row).
        resp = auth_client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code == 503
        _assert_envelope(resp)


# ---- Authentication guard -----------------------------------------------


class TestAuthGuard:
    def test_anonymous_account_get_redirects_to_login(self, db):
        client = Client()
        resp = client.get("/api/calendar/account/")
        assert resp.status_code in (302, 401, 403)

    def test_anonymous_events_redirects_to_login(self, db):
        client = Client()
        resp = client.get("/api/calendar/events/2026-05-07/")
        assert resp.status_code in (302, 401, 403)
