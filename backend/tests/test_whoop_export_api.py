"""``GET /api/export/whoop/<date>/`` (feature 0107, step 11).

Authenticates like the daily export (Bearer export token or session), maps
the date to WHOOP records and returns the Markdown summary. WHOOP data is
neither stored, cached nor logged, and provider bodies never reach the client.
"""

import datetime
import json
import logging
from pathlib import Path

import httpx
import pytest
import respx
from django.contrib.auth.models import User
from django.core.cache import cache
from schedules import export_auth, window
from schedules.export_tokens import create_token
from schedules.models import UserScheduleSettings
from whoop_sync.models import WhoopAccount

from tests.test_whoop_sync_formatting import PLAN_EXAMPLE
from tests.whoop_helpers import API_BASE, TOKEN_URI, WHOOP_SETTINGS

pytestmark = pytest.mark.django_db

SYNTHETIC = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "whoop" / "synthetic_2026-11-23.json")
    .read_text()
)
FAR_FUTURE = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)


def _url(date):
    return f"/api/export/whoop/{date}/"


def _bearer(token):
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _whoop_settings(settings):
    for name, value in WHOOP_SETTINGS.items():
        setattr(settings, name, value)
    cache.clear()


@pytest.fixture
def owner(user):
    UserScheduleSettings.objects.create(
        user=user, day_start=datetime.time(6), day_end=datetime.time(23),
        time_zone="Asia/Almaty",
    )
    return user


@pytest.fixture
def raw_token(owner):
    token, _ = create_token(owner.pk)
    return token


@pytest.fixture
def account(owner):
    acc = WhoopAccount(user=owner, scopes="offline read:sleep")
    acc.set_refresh_token("refresh-0")
    acc.set_access_token("access-0")
    acc.access_token_expiry = FAR_FUTURE
    acc.save()
    return acc


@pytest.fixture
def whoop_api():
    with respx.mock(assert_all_called=False) as mock:
        routes = {
            "sleep": mock.get(f"{API_BASE}/v2/activity/sleep").respond(
                200, json={"records": SYNTHETIC["sleeps"], "next_token": None}
            ),
            "cycle": mock.get(f"{API_BASE}/v2/cycle").respond(
                200, json={"records": SYNTHETIC["cycles_before_sleep"], "next_token": None}
            ),
            "recovery": mock.get(f"{API_BASE}/v2/cycle/1002/recovery").respond(
                200, json=SYNTHETIC["recovery"]
            ),
            "workout": mock.get(f"{API_BASE}/v2/activity/workout").respond(
                200, json={"records": SYNTHETIC["workouts"], "next_token": None}
            ),
            "token": mock.post(TOKEN_URI).respond(500),
        }
        yield routes


class TestSuccess:
    def test_bearer_returns_the_markdown_summary(self, client, account, raw_token, whoop_api):
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 200
        assert response.content.decode() == PLAN_EXAMPLE
        assert response["Content-Type"] == "text/markdown; charset=utf-8"
        assert response["Cache-Control"] == "private, no-store"
        sleep_params = whoop_api["sleep"].calls.last.request.url.params
        assert sleep_params["start"] == "2026-11-22T07:00:00.000Z"
        assert sleep_params["end"] == "2026-11-23T07:00:00.000Z"

    def test_session_also_works(self, auth_client, account, owner, whoop_api):
        response = auth_client.get(_url("2026-11-23"))
        assert response.status_code == 200
        assert response.content.decode() == PLAN_EXAMPLE

    def test_today_resolves_in_the_owners_saved_zone(
        self, client, account, raw_token, whoop_api, monkeypatch
    ):
        # 20:30 UTC on 22 Nov is already 23 Nov in Asia/Almaty (UTC+5).
        frozen = datetime.datetime(2026, 11, 22, 20, 30, tzinfo=datetime.UTC)
        monkeypatch.setattr(window.timezone, "now", lambda: frozen)
        response = client.get(_url("today"), **_bearer(raw_token))
        assert response.status_code == 200
        assert response.content.decode().startswith("## whoop · 2026-11-23\n")

    def test_stores_caches_and_logs_no_whoop_data(
        self, client, account, raw_token, whoop_api, caplog
    ):
        caplog.set_level(logging.DEBUG)
        before = WhoopAccount.objects.get(pk=account.pk)
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 200
        after = WhoopAccount.objects.get(pk=account.pk)
        assert after.updated_at == before.updated_at
        assert cache._cache == {}  # LocMemCache: nothing was cached
        for value in ("31.1", "16.4", "HIIT", "sleep-main", "access-0", "refresh-0"):
            assert value not in caplog.text


class TestAuthentication:
    def test_anonymous_is_401_json_without_whoop_calls(self, client, account, whoop_api):
        response = client.get(_url("2026-11-23"))
        assert response.status_code == 401
        assert response["Cache-Control"] == "private, no-store"
        assert response.get("Location") is None
        assert whoop_api["sleep"].called is False

    def test_invalid_bearer_is_401_even_with_session(self, auth_client, account, whoop_api):
        response = auth_client.get(_url("2026-11-23"), HTTP_AUTHORIZATION="Bearer nope")
        assert response.status_code == 401

    def test_bearer_selects_its_owner_not_the_session_user(
        self, auth_client, account, whoop_api
    ):
        other = User.objects.create_user(username="other-owner")
        token, _ = create_token(other.pk)
        response = auth_client.get(_url("2026-11-23"), **_bearer(token))
        assert response.status_code == 404  # the other owner has no WHOOP account

    def test_route_is_in_the_bearer_allowlist(self):
        assert export_auth.BEARER_ROUTE_NAMES == frozenset({"daily_export", "whoop_export"})


class TestErrors:
    @pytest.mark.parametrize("date", ["2026-13-01", "20261123", "tomorrow", "2026-02-30"])
    def test_bad_date_is_400(self, client, account, raw_token, whoop_api, date):
        response = client.get(_url(date), **_bearer(raw_token))
        assert response.status_code == 400
        assert response["Cache-Control"] == "private, no-store"
        assert whoop_api["sleep"].called is False

    def test_not_connected_is_404_without_whoop_calls(self, client, raw_token, whoop_api):
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 404
        assert response.json()["errors"]["detail"] == "WHOOP is not connected."
        assert response["Cache-Control"] == "private, no-store"
        assert whoop_api["sleep"].called is False

    def test_not_configured_is_404(self, client, account, raw_token, whoop_api, settings):
        for name in WHOOP_SETTINGS:
            setattr(settings, name, "")
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 404
        assert response.json()["errors"]["detail"] == "WHOOP is not configured."
        assert whoop_api["sleep"].called is False

    def test_rejected_refresh_is_409(self, client, account, raw_token, whoop_api):
        account.access_token_expiry = None
        account.save()
        whoop_api["token"].respond(400, json={"error": "invalid_grant"})
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 409
        assert response.json()["errors"]["detail"] == "WHOOP needs to be reconnected."

    def test_unreadable_stored_token_is_409(self, client, account, raw_token, whoop_api, settings):
        from cryptography.fernet import Fernet

        settings.WHOOP_OAUTH_TOKEN_KEY = Fernet.generate_key().decode()
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 409

    def test_rate_limit_is_429(self, client, account, raw_token, whoop_api):
        whoop_api["sleep"].respond(429, text="PROVIDER_BODY")
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 429
        assert "PROVIDER_BODY" not in response.content.decode()

    @pytest.mark.parametrize("failure", [
        httpx.Response(503, text="PROVIDER_BODY"),
        httpx.ConnectError("down"),
    ], ids=["5xx", "unreachable"])
    def test_provider_failure_is_502_without_the_body(
        self, client, account, raw_token, whoop_api, failure
    ):
        if isinstance(failure, Exception):
            whoop_api["recovery"].mock(side_effect=failure)
        else:
            whoop_api["recovery"].mock(return_value=failure)
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 502
        assert response["Cache-Control"] == "private, no-store"
        assert "PROVIDER_BODY" not in response.content.decode()

    def test_waiter_timeout_is_502_not_409(
        self, client, account, raw_token, whoop_api, monkeypatch
    ):
        from whoop_sync import service

        account.access_token_expiry = None
        account.save()
        cache.add(service.refresh_lock_key(account.pk), "other-holder", timeout=60)
        monkeypatch.setattr(service, "_sleep", lambda seconds: None)
        monkeypatch.setattr(service, "_lock_timeout_seconds", lambda: 0)
        response = client.get(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 502

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_non_get_is_405(self, client, account, raw_token, method):
        response = getattr(client, method)(_url("2026-11-23"), **_bearer(raw_token))
        assert response.status_code == 405


def test_ai_packages_never_import_whoop():
    backend = Path(__file__).resolve().parents[1]
    for path in (backend / "ai").rglob("*.py"):
        assert "whoop" not in path.read_text().lower(), path
