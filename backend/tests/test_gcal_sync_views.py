"""View/route tests for ``gcal_sync.views``.

The async events view is exercised through Django's test ``Client`` (which
runs async views). Service calls are patched at ``views.service.*`` so no
network or google-auth machinery runs.
"""

import datetime
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from calendar_sync.schemas import NormalizedEvent
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone as django_tz
from gcal_sync import cache as gcal_cache
from gcal_sync import views
from gcal_sync.models import GoogleCalendarAccount

FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _gcal_settings(settings):
    settings.GOOGLE_OAUTH_TOKEN_KEY = FERNET_KEY
    settings.GOOGLE_OAUTH_CLIENT_ID = "client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "client-secret"
    settings.GOOGLE_OAUTH_REDIRECT_URI = "https://app.test/api/calendar/google/callback/"
    settings.GOOGLE_CACHE_TTL_SECONDS = 300
    settings.TIME_ZONE = "UTC"


def _make_account(user, *, google_account_id="sub-1", email="alice@gmail.com"):
    acc = GoogleCalendarAccount(
        user=user, google_account_id=google_account_id, email=email
    )
    acc.set_refresh_token("refresh-abc")
    acc.set_access_token("access-xyz")
    acc.access_token_expiry = django_tz.now() + timedelta(hours=1)
    acc.save()
    return acc


def _ev(title, start_iso):
    start = datetime.datetime.fromisoformat(start_iso)
    return NormalizedEvent(
        title=title,
        start=start,
        end=start + timedelta(hours=1),
        calendar_name="Primary",
        all_day=False,
        external_uid=f"{title}@google",
        account_label="alice@gmail.com",
    )


# ----- connect / callback ------------------------------------------------


class TestConnect:
    def test_connect_redirects_and_stores_state(self, auth_client):
        resp = auth_client.get("/api/calendar/google/connect/")
        assert resp.status_code == 302
        assert "accounts.google.com" in resp["Location"]
        assert auth_client.session.get("gcal_oauth_state")


class TestCallback:
    def _set_state(self, client, state):
        session = client.session
        session["gcal_oauth_state"] = state
        session.save()

    def test_state_mismatch_rejected(self, auth_client, db):
        self._set_state(auth_client, "good")
        resp = auth_client.get(
            "/api/calendar/google/callback/?state=evil&code=abc"
        )
        assert resp.status_code == 302
        assert "google=error&reason=state" in resp["Location"]
        assert GoogleCalendarAccount.objects.count() == 0

    def test_missing_state_rejected(self, auth_client, db):
        resp = auth_client.get("/api/calendar/google/callback/?code=abc")
        assert "google=error&reason=state" in resp["Location"]
        assert GoogleCalendarAccount.objects.count() == 0

    def test_denied_redirects(self, auth_client, db):
        self._set_state(auth_client, "st")
        resp = auth_client.get(
            "/api/calendar/google/callback/?state=st&error=access_denied"
        )
        assert "google=error&reason=denied" in resp["Location"]
        assert GoogleCalendarAccount.objects.count() == 0

    def test_missing_code_redirects(self, auth_client, db):
        self._set_state(auth_client, "st")
        resp = auth_client.get("/api/calendar/google/callback/?state=st")
        assert "google=error&reason=missing_code" in resp["Location"]
        assert GoogleCalendarAccount.objects.count() == 0

    def test_successful_callback_upserts(self, auth_client, user):
        self._set_state(auth_client, "st")
        info = {
            "google_account_id": "sub-9",
            "email": "bob@gmail.com",
            "refresh_token": "r-1",
            "access_token": "a-1",
            "expiry": django_tz.now() + timedelta(hours=1),
        }
        with patch.object(views.service, "exchange_code", return_value=info):
            resp = auth_client.get(
                "/api/calendar/google/callback/?state=st&code=the-code"
            )
        assert "google=connected" in resp["Location"]
        acc = GoogleCalendarAccount.objects.get(user=user, google_account_id="sub-9")
        assert acc.email == "bob@gmail.com"
        assert acc.get_refresh_token() == "r-1"

    def test_reconnect_same_account_updates_in_place(self, auth_client, user):
        base = {
            "google_account_id": "sub-9",
            "access_token": "a",
            "expiry": django_tz.now() + timedelta(hours=1),
        }
        info1 = {**base, "email": "bob@gmail.com", "refresh_token": "r-2"}
        # Reconnect with a NEW email + rotated refresh token, same Google id.
        info2 = {**base, "email": "bob-new@gmail.com", "refresh_token": "r-3"}
        for info in (info1, info2):
            self._set_state(auth_client, "st")
            with patch.object(views.service, "exchange_code", return_value=info):
                auth_client.get(
                    "/api/calendar/google/callback/?state=st&code=the-code"
                )
        qs = GoogleCalendarAccount.objects.filter(
            user=user, google_account_id="sub-9"
        )
        assert qs.count() == 1  # no duplicate row
        acc = qs.get()
        # Upsert updated the existing row to the latest values.
        assert acc.email == "bob-new@gmail.com"
        assert acc.get_refresh_token() == "r-3"

    def test_provider_error_redirects(self, auth_client, db):
        self._set_state(auth_client, "st")
        with patch.object(
            views.service,
            "exchange_code",
            side_effect=views.service.GoogleCalProviderError("boom"),
        ):
            resp = auth_client.get(
                "/api/calendar/google/callback/?state=st&code=the-code"
            )
        assert "google=error&reason=provider" in resp["Location"]


# ----- accounts list / disconnect ----------------------------------------


class TestAccounts:
    def test_list_accounts(self, auth_client, user):
        _make_account(user, google_account_id="s1", email="a@gmail.com")
        _make_account(user, google_account_id="s2", email="b@gmail.com")
        resp = auth_client.get("/api/calendar/google/accounts/")
        data = resp.json()
        assert {a["email"] for a in data["accounts"]} == {"a@gmail.com", "b@gmail.com"}
        # no token field ever
        assert all("refresh_token" not in a for a in data["accounts"])

    def test_disconnect_scoped_to_user_idor(self, auth_client, user):
        other = User.objects.create_user(username="other", password="x")
        other_acc = _make_account(other, google_account_id="o1", email="o@gmail.com")
        resp = auth_client.delete(
            f"/api/calendar/google/accounts/{other_acc.id}/"
        )
        assert resp.status_code == 200
        # other user's account is untouched (IDOR guard)
        assert GoogleCalendarAccount.objects.filter(id=other_acc.id).exists()

    def test_disconnect_own_account(self, auth_client, user):
        acc = _make_account(user)
        resp = auth_client.delete(f"/api/calendar/google/accounts/{acc.id}/")
        assert resp.status_code == 200
        assert resp.json()["accounts"] == []
        assert not GoogleCalendarAccount.objects.filter(id=acc.id).exists()


# ----- events (async multi-account) --------------------------------------


class TestEvents:
    def test_no_accounts_returns_503(self, auth_client, db):
        resp = auth_client.get("/api/calendar/google/events/2026-05-07/")
        assert resp.status_code == 503

    def test_invalid_date_returns_400(self, auth_client, user):
        _make_account(user)
        resp = auth_client.get("/api/calendar/google/events/not-a-date/")
        assert resp.status_code == 400

    def test_multi_account_merge(self, auth_client, user):
        _make_account(user, google_account_id="s1", email="a@gmail.com")
        _make_account(user, google_account_id="s2", email="b@gmail.com")

        async def fake_fetch(acc, td):
            return [_ev(f"Ev-{acc.email}", "2026-05-07T09:00:00+00:00")]

        with patch.object(views.service, "fetch_events_for_account", fake_fetch):
            resp = auth_client.get("/api/calendar/google/events/2026-05-07/")
        data = resp.json()
        assert resp.status_code == 200
        assert len(data["events"]) == 2
        assert data["account_errors"] == []

    def test_partial_success(self, auth_client, user):
        _make_account(user, google_account_id="s1", email="good@gmail.com")
        _make_account(user, google_account_id="s2", email="bad@gmail.com")

        async def fake_fetch(acc, td):
            if acc.email == "good@gmail.com":
                return [_ev("Healthy", "2026-05-07T09:00:00+00:00")]
            raise views.service.GoogleCalAuthError("revoked")

        with patch.object(views.service, "fetch_events_for_account", fake_fetch):
            resp = auth_client.get("/api/calendar/google/events/2026-05-07/")
        data = resp.json()
        assert resp.status_code == 200
        assert [e["title"] for e in data["events"]] == ["Healthy"]
        assert len(data["account_errors"]) == 1
        assert data["account_errors"][0]["error"] == "reconnect_required"
        assert data["account_errors"][0]["email"] == "bad@gmail.com"

    def test_provider_failure_is_unavailable(self, auth_client, user):
        _make_account(user, google_account_id="s1", email="a@gmail.com")

        async def fake_fetch(acc, td):
            raise views.service.GoogleCalProviderError("boom")

        with patch.object(views.service, "fetch_events_for_account", fake_fetch):
            resp = auth_client.get("/api/calendar/google/events/2026-05-07/")
        data = resp.json()
        assert resp.status_code == 200
        assert data["account_errors"][0]["error"] == "unavailable"

    def test_timeout_failure_is_unavailable(self, auth_client, user):
        _make_account(user, google_account_id="s1", email="a@gmail.com")

        async def fake_fetch(acc, td):
            raise views.service.GoogleCalTimeoutError("slow")

        with patch.object(views.service, "fetch_events_for_account", fake_fetch):
            resp = auth_client.get("/api/calendar/google/events/2026-05-07/")
        data = resp.json()
        assert resp.status_code == 200
        assert data["account_errors"][0]["error"] == "unavailable"

    def test_mixed_cache_hit_and_per_account_auth_failure(self, auth_client, user):
        import asyncio

        acc_cached = _make_account(user, google_account_id="s1", email="cached@gmail.com")
        _make_account(user, google_account_id="s2", email="bad@gmail.com")
        payload = [
            {
                "title": "Cached",
                "start": "2026-05-07T09:00:00+00:00",
                "end": "2026-05-07T10:00:00+00:00",
                "calendar_name": "Primary",
                "all_day": False,
                "external_uid": "cached@google",
                "account_label": "cached@gmail.com",
            }
        ]
        asyncio.run(
            gcal_cache.set_cached_events(acc_cached, datetime.date(2026, 5, 7), payload)
        )

        async def fake_fetch(acc, td):
            # Only the uncached (bad) account reaches the service.
            raise views.service.GoogleCalAuthError("revoked")

        with patch.object(views.service, "fetch_events_for_account", fake_fetch):
            resp = auth_client.get("/api/calendar/google/events/2026-05-07/")
        data = resp.json()
        assert resp.status_code == 200
        # Cache-served account's events present...
        assert [e["title"] for e in data["events"]] == ["Cached"]
        # ...alongside the uncached account's reconnect error.
        assert len(data["account_errors"]) == 1
        assert data["account_errors"][0]["email"] == "bad@gmail.com"
        assert data["account_errors"][0]["error"] == "reconnect_required"

    def test_improperly_configured_returns_500(self, auth_client, user):
        _make_account(user)

        async def fake_fetch(acc, td):
            from django.core.exceptions import ImproperlyConfigured

            raise ImproperlyConfigured("key rotated")

        with patch.object(views.service, "fetch_events_for_account", fake_fetch):
            resp = auth_client.get("/api/calendar/google/events/2026-05-07/")
        assert resp.status_code == 500
        assert "misconfigured" in resp.json()["errors"]["detail"]

    def test_cache_hit_short_circuits(self, auth_client, user):
        import asyncio

        acc = _make_account(user)
        payload = [
            {
                "title": "Cached",
                "start": "2026-05-07T09:00:00+00:00",
                "end": "2026-05-07T10:00:00+00:00",
                "calendar_name": "Primary",
                "all_day": False,
                "external_uid": "cached@google",
                "account_label": "alice@gmail.com",
            }
        ]
        asyncio.run(
            gcal_cache.set_cached_events(acc, datetime.date(2026, 5, 7), payload)
        )
        mock = MagicMock()
        with patch.object(views.service, "fetch_events_for_account", mock):
            resp = auth_client.get("/api/calendar/google/events/2026-05-07/")
        data = resp.json()
        assert [e["title"] for e in data["events"]] == ["Cached"]
        mock.assert_not_called()  # served entirely from cache

    def test_parsed_date_contract(self, auth_client, user):
        _make_account(user)
        captured = {}

        async def fake_fetch(acc, td):
            captured["td"] = td
            return []

        with patch.object(views.service, "fetch_events_for_account", fake_fetch):
            auth_client.get("/api/calendar/google/events/2026-05-07/")
        assert captured["td"] == datetime.date(2026, 5, 7)
        assert isinstance(captured["td"], datetime.date)


class TestAuthGuards:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", "/api/calendar/google/connect/"),
            ("get", "/api/calendar/google/callback/"),
            ("get", "/api/calendar/google/accounts/"),
            ("delete", "/api/calendar/google/accounts/1/"),
            ("get", "/api/calendar/google/events/2026-05-07/"),
        ],
    )
    def test_requires_login(self, db, method, path):
        client = Client()
        resp = getattr(client, method)(path)
        # login_required → redirect to the login URL
        assert resp.status_code == 302
        assert "/accounts/login/" in resp["Location"]
