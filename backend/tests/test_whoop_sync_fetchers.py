"""WHOOP REST fetchers: sleep, cycle, recovery, workout (feature 0107, step 8)."""

import datetime
import logging

import httpx
import pytest
import respx
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from whoop_sync import service
from whoop_sync.models import WhoopAccount

from tests.whoop_helpers import API_BASE, TOKEN_URI, WHOOP_SETTINGS, token_body

pytestmark = pytest.mark.django_db

UTC = datetime.UTC
START = datetime.datetime(2026, 11, 22, 7, 0, tzinfo=UTC)
END = datetime.datetime(2026, 11, 23, 7, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _whoop_settings(settings):
    for name, value in WHOOP_SETTINGS.items():
        setattr(settings, name, value)
    cache.clear()


@pytest.fixture
def account(db):
    user = User.objects.create_user(username="whoop-fetch")
    acc = WhoopAccount(user=user)
    acc.set_refresh_token("refresh-0")
    acc.set_access_token("access-0")
    acc.access_token_expiry = timezone.now() + datetime.timedelta(hours=1)
    acc.save()
    return acc


class TestCollections:
    @respx.mock
    def test_sleep_window_params_bearer_and_user_agent(self, account):
        route = respx.get(f"{API_BASE}/v2/activity/sleep").respond(
            200, json={"records": [{"id": "s1"}], "next_token": None}
        )
        assert service.fetch_sleeps(account, START, END) == [{"id": "s1"}]
        request = route.calls.last.request
        assert request.url.params["start"] == "2026-11-22T07:00:00.000Z"
        assert request.url.params["end"] == "2026-11-23T07:00:00.000Z"
        assert request.url.params["limit"] == "25"
        assert "nextToken" not in request.url.params
        assert request.headers["authorization"] == "Bearer access-0"
        assert request.headers["user-agent"] == "day-forge"

    @respx.mock
    def test_follows_next_token(self, account):
        route = respx.get(f"{API_BASE}/v2/activity/workout").mock(side_effect=[
            httpx.Response(200, json={"records": [{"id": 1}], "next_token": "page-2"}),
            httpx.Response(200, json={"records": [{"id": 2}], "next_token": None}),
        ])
        assert service.fetch_workouts(account, START, END) == [{"id": 1}, {"id": 2}]
        assert route.calls[1].request.url.params["nextToken"] == "page-2"

    @respx.mock
    def test_page_cap_stops_a_runaway_cursor(self, account):
        route = respx.get(f"{API_BASE}/v2/activity/workout").respond(
            200, json={"records": [{"id": 1}], "next_token": "again"}
        )
        with pytest.raises(service.WhoopProviderError):
            service.fetch_workouts(account, START, END)
        assert route.call_count == service.MAX_PAGES

    @respx.mock
    def test_cycles_before_a_time(self, account):
        route = respx.get(f"{API_BASE}/v2/cycle").respond(
            200, json={"records": [{"id": 9}, {"id": 8}], "next_token": "more"}
        )
        assert service.fetch_cycles_ending_by(account, END, limit=2) == [{"id": 9}, {"id": 8}]
        params = route.calls.last.request.url.params
        assert params["end"] == "2026-11-23T07:00:00.000Z"
        assert params["limit"] == "2"
        assert "start" not in params
        assert route.call_count == 1  # a bounded lookup never pages

    @pytest.mark.parametrize("body", [[], {"records": "x"}, {"records": [1]}, {"no": "records"}])
    @respx.mock
    def test_malformed_collection_is_a_provider_error(self, account, body):
        respx.get(f"{API_BASE}/v2/activity/sleep").respond(200, json=body)
        with pytest.raises(service.WhoopProviderError):
            service.fetch_sleeps(account, START, END)


class TestRecovery:
    @respx.mock
    def test_recovery_for_cycle(self, account):
        respx.get(f"{API_BASE}/v2/cycle/93845/recovery").respond(
            200, json={"cycle_id": 93845, "score_state": "SCORED"}
        )
        assert service.fetch_recovery(account, 93845)["cycle_id"] == 93845

    @respx.mock
    def test_missing_recovery_is_none(self, account):
        respx.get(f"{API_BASE}/v2/cycle/93845/recovery").respond(404)
        assert service.fetch_recovery(account, 93845) is None


class TestErrors:
    @respx.mock
    def test_401_refreshes_once_and_retries(self, account):
        token = respx.post(TOKEN_URI).respond(200, json=token_body(access="access-1"))
        api = respx.get(f"{API_BASE}/v2/activity/sleep").mock(side_effect=[
            httpx.Response(401),
            httpx.Response(200, json={"records": [], "next_token": None}),
        ])
        assert service.fetch_sleeps(account, START, END) == []
        assert token.call_count == 1
        assert api.calls[1].request.headers["authorization"] == "Bearer access-1"

    @respx.mock
    def test_second_401_requires_reconnect(self, account):
        respx.post(TOKEN_URI).respond(200, json=token_body(access="access-1"))
        respx.get(f"{API_BASE}/v2/activity/sleep").respond(401)
        with pytest.raises(service.WhoopAuthError):
            service.fetch_sleeps(account, START, END)

    @pytest.mark.parametrize("status,error", [
        (429, service.WhoopRateLimitError),
        (500, service.WhoopProviderError),
        (503, service.WhoopProviderError),
        (404, service.WhoopProviderError),
    ])
    @respx.mock
    def test_status_mapping(self, account, status, error):
        respx.get(f"{API_BASE}/v2/activity/sleep").respond(status, text="PROVIDER_BODY")
        with pytest.raises(error) as excinfo:
            service.fetch_sleeps(account, START, END)
        assert "PROVIDER_BODY" not in str(excinfo.value)

    @respx.mock
    def test_network_failure(self, account):
        respx.get(f"{API_BASE}/v2/cycle/1/recovery").mock(side_effect=httpx.ReadTimeout("t"))
        with pytest.raises(service.WhoopProviderError):
            service.fetch_recovery(account, 1)

    @respx.mock
    def test_non_json_body(self, account):
        respx.get(f"{API_BASE}/v2/cycle/1/recovery").respond(200, content=b"<html>")
        with pytest.raises(service.WhoopProviderError):
            service.fetch_recovery(account, 1)

    @respx.mock
    def test_health_data_is_not_logged(self, account, caplog):
        caplog.set_level(logging.DEBUG)
        respx.get(f"{API_BASE}/v2/cycle/1/recovery").respond(
            200, json={"cycle_id": 1, "score": {"hrv_rmssd_milli": 31.123456}}
        )
        service.fetch_recovery(account, 1)
        assert "31.123456" not in caplog.text
        assert "access-0" not in caplog.text
