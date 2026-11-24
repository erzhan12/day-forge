"""WHOOP token lifecycle: rotation and the single-flight refresh lock
(feature 0107, step 7).

The concurrency tests run in a subprocess on a copy of the test database,
where each thread holds its own SQLite connection (RULES.md, UI and
verification exceptions), and include a competing writer reservation.
"""

import datetime
import json
import logging
import urllib.parse

import httpx
import pytest
import respx
from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils import timezone
from whoop_sync import service
from whoop_sync.models import WhoopAccount

from tests.test_schedule_mutations_sqlite import copied_database, run_on_copy  # noqa: F401
from tests.whoop_helpers import TOKEN_URI, WHOOP_SETTINGS, token_body


@pytest.fixture(autouse=True)
def _whoop_settings(settings):
    for name, value in WHOOP_SETTINGS.items():
        setattr(settings, name, value)
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def no_sleep(monkeypatch):
    calls = []
    monkeypatch.setattr(service, "_sleep", lambda seconds: calls.append(seconds))
    return calls


def _account(*, access="old-access", refresh="old-refresh", expires_in=-60):
    user = User.objects.create_user(username=f"whoop-{User.objects.count()}")
    account = WhoopAccount(user=user)
    account.set_refresh_token(refresh)
    account.set_access_token(access)
    account.access_token_expiry = timezone.now() + datetime.timedelta(seconds=expires_in)
    account.save()
    return account


def _store(account, *, access, refresh=None, expires_in=3600):
    row = WhoopAccount.objects.get(pk=account.pk)
    row.set_access_token(access)
    if refresh is not None:
        row.set_refresh_token(refresh)
    row.access_token_expiry = timezone.now() + datetime.timedelta(seconds=expires_in)
    row.save()


pytestmark = pytest.mark.django_db


class TestCachedAccessToken:
    @respx.mock
    def test_valid_token_is_used_without_a_refresh(self):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        account = _account(access="still-good", expires_in=600)
        assert service.ensure_access_token(account) == "still-good"
        assert route.called is False

    @respx.mock
    def test_token_inside_the_120s_skew_is_refreshed(self):
        route = respx.post(TOKEN_URI).respond(200, json=token_body(access="new"))
        account = _account(access="nearly-expired", expires_in=100)
        assert service.ensure_access_token(account) == "new"
        assert route.call_count == 1


class TestLockHolder:
    @respx.mock
    def test_persists_rotated_refresh_token_and_releases_the_lock(self):
        route = respx.post(TOKEN_URI).respond(
            200, json=token_body(access="new-access", refresh="new-refresh")
        )
        account = _account()
        assert service.ensure_access_token(account) == "new-access"

        form = urllib.parse.parse_qs(route.calls.last.request.content.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["old-refresh"]
        assert form["scope"] == ["offline"]
        assert route.calls.last.request.headers["user-agent"] == "day-forge"

        row = WhoopAccount.objects.get(pk=account.pk)
        assert row.get_refresh_token() == "new-refresh"
        assert row.get_access_token() == "new-access"
        assert row.access_token_expiry > timezone.now() + datetime.timedelta(minutes=50)
        assert cache.get(service.refresh_lock_key(account.pk)) is None

    @respx.mock
    def test_lock_key_is_per_account(self):
        assert service.refresh_lock_key(42) == "whoop_refresh:42"

    @respx.mock
    def test_missing_refresh_token_in_response_keeps_the_stored_one(self):
        respx.post(TOKEN_URI).respond(200, json=token_body(access="new", refresh=None))
        account = _account()
        service.ensure_access_token(account)
        assert WhoopAccount.objects.get(pk=account.pk).get_refresh_token() == "old-refresh"

    @respx.mock
    def test_holder_rechecks_the_row_before_refreshing(self):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        account = _account()
        _store(account, access="refreshed-elsewhere")
        assert service.ensure_access_token(account) == "refreshed-elsewhere"
        assert route.called is False

    @pytest.mark.parametrize("status", [400, 401])
    @respx.mock
    def test_rejected_refresh_without_fresher_token_requires_reconnect(self, status):
        respx.post(TOKEN_URI).respond(status, json={"error": "invalid_grant"})
        account = _account()
        with pytest.raises(service.WhoopAuthError):
            service.ensure_access_token(account)
        assert cache.get(service.refresh_lock_key(account.pk)) is None

    @respx.mock
    def test_rejected_refresh_recovers_a_fresher_stored_token(self):
        account = _account()

        def rotated_by_a_slow_earlier_holder(request):
            _store(account, access="stored-by-other", refresh="rotated-by-other")
            return httpx.Response(400, json={"error": "invalid_grant"})

        respx.post(TOKEN_URI).mock(side_effect=rotated_by_a_slow_earlier_holder)
        assert service.ensure_access_token(account) == "stored-by-other"

    @pytest.mark.parametrize("status,error", [
        (429, service.WhoopRateLimitError),
        (500, service.WhoopProviderError),
    ])
    @respx.mock
    def test_transient_refresh_failures_release_the_lock(self, status, error):
        respx.post(TOKEN_URI).respond(status)
        account = _account()
        with pytest.raises(error):
            service.ensure_access_token(account)
        assert cache.get(service.refresh_lock_key(account.pk)) is None
        row = WhoopAccount.objects.get(pk=account.pk)
        assert row.get_refresh_token() == "old-refresh"

    @respx.mock
    def test_never_logs_tokens_or_bodies(self, caplog):
        caplog.set_level(logging.DEBUG)
        respx.post(TOKEN_URI).respond(200, json=token_body(access="new-a", refresh="new-r"))
        service.ensure_access_token(_account())
        respx.post(TOKEN_URI).respond(400, text="BODY")
        with pytest.raises(service.WhoopAuthError):
            service.ensure_access_token(_account())
        for secret in ("old-refresh", "new-a", "new-r", "BODY", "whoop-client-secret"):
            assert secret not in caplog.text


class TestWaiter:
    @respx.mock
    def test_waiter_picks_up_the_token_the_holder_stores(self, no_sleep, monkeypatch):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        account = _account()
        cache.add(service.refresh_lock_key(account.pk), "other-holder", timeout=60)

        def holder_finishes(seconds):
            no_sleep.append(seconds)
            if len(no_sleep) == 2:
                _store(account, access="holder-token", refresh="holder-refresh")

        monkeypatch.setattr(service, "_sleep", holder_finishes)
        assert service.ensure_access_token(account) == "holder-token"
        assert route.called is False
        assert no_sleep == [service.POLL_INTERVAL_SECONDS] * 2

    @respx.mock
    def test_waiter_times_out_as_transient_not_reconnect(self, no_sleep, monkeypatch):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        account = _account()
        cache.add(service.refresh_lock_key(account.pk), "stuck-holder", timeout=60)
        clock = iter(range(0, 10_000, 1))
        monkeypatch.setattr(service.time, "monotonic", lambda: next(clock))
        with pytest.raises(service.WhoopProviderError) as excinfo:
            service.ensure_access_token(account)
        assert not isinstance(excinfo.value, service.WhoopAuthError)
        assert route.called is False
        assert cache.get(service.refresh_lock_key(account.pk)) == "stuck-holder"

    @respx.mock
    def test_waiter_stops_when_the_holder_fails(self, monkeypatch):
        account = _account()
        key = service.refresh_lock_key(account.pk)
        cache.add(key, "failing-holder", timeout=60)
        monkeypatch.setattr(service, "_sleep", lambda seconds: cache.delete(key))
        with pytest.raises(service.WhoopProviderError):
            service.ensure_access_token(account)


    @respx.mock
    def test_waiter_rechecks_the_row_when_the_lock_disappears(self, no_sleep, monkeypatch):
        # The holder can store its token and release the lock between the
        # waiter's row read and its lock check; that must not become a 502.
        account = _account()
        key = service.refresh_lock_key(account.pk)
        cache.add(key, "fast-holder", timeout=60)
        real_reload = service._reload
        reads = []

        def reload_then_holder_finishes(account_id):
            row = real_reload(account_id)
            reads.append(account_id)
            if len(reads) == 1:
                _store(account, access="stored-just-now", refresh="rotated")
                cache.delete(key)
            return row

        monkeypatch.setattr(service, "_reload", reload_then_holder_finishes)
        assert service.ensure_access_token(account) == "stored-just-now"


class TestRejectedAccessToken:
    @respx.mock
    def test_forced_refresh_ignores_a_valid_looking_rejected_token(self):
        route = respx.post(TOKEN_URI).respond(200, json=token_body(access="after-401"))
        account = _account(access="revoked", expires_in=600)
        assert service.ensure_access_token(account, rejected="revoked") == "after-401"
        assert route.call_count == 1

    @respx.mock
    def test_forced_refresh_uses_a_different_stored_token(self):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        account = _account(access="revoked", expires_in=600)
        _store(account, access="already-rotated")
        assert service.ensure_access_token(account, rejected="revoked") == "already-rotated"
        assert route.called is False


# --------------------------------------------------------------------------
# Independent SQLite connections
# --------------------------------------------------------------------------

_SUBPROCESS_SETUP = """
import datetime, json, threading, time
import httpx, respx
from django.contrib.auth.models import User
from django.db import connections
from django.utils import timezone
settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
for name, value in json.loads(WHOOP_SETTINGS).items():
    setattr(settings, name, value)
from whoop_sync import service
from whoop_sync.models import WhoopAccount
TOKEN_URI = 'https://api.prod.whoop.com/oauth/oauth2/token'
user = User.objects.create_user(username='whoop-race')
account = WhoopAccount(user=user)
account.set_refresh_token('old-refresh')
account.set_access_token('old-access')
account.access_token_expiry = timezone.now() - datetime.timedelta(minutes=5)
account.save()
"""


def _script(body: str) -> str:
    return (
        "WHOOP_SETTINGS = " + repr(json.dumps(WHOOP_SETTINGS)) + "\n"
        + _SUBPROCESS_SETUP + body
    )


def test_concurrent_requests_refresh_once_on_separate_sqlite_connections(copied_database):  # noqa: F811
    run_on_copy(copied_database, _script("""
calls = []
def token_endpoint(request):
    calls.append(threading.get_ident())
    time.sleep(0.4)  # hold the lock long enough for the other request to wait
    return httpx.Response(200, json={
        'access_token': 'new-access', 'refresh_token': 'new-refresh',
        'expires_in': 3600, 'scope': 'offline',
    })

barrier = threading.Barrier(2)
results, errors = [], []
def request():
    try:
        mine = WhoopAccount.objects.get(pk=account.pk)  # this thread's own connection
        barrier.wait()
        results.append(service.ensure_access_token(mine))
    except Exception as exc:
        errors.append(repr(exc))
    finally:
        connections.close_all()

with respx.mock:
    respx.post(TOKEN_URI).mock(side_effect=token_endpoint)
    threads = [threading.Thread(target=request) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
assert not errors, errors
assert len(calls) == 1, calls
assert results == ['new-access', 'new-access'], results
row = WhoopAccount.objects.get(pk=account.pk)
assert row.get_refresh_token() == 'new-refresh'
"""))


def test_holder_persists_through_a_competing_writer_reservation(copied_database):  # noqa: F811
    run_on_copy(copied_database, _script("""
import sqlite3
holders = []
def token_endpoint(request):
    # An independent connection reserves the SQLite writer just before the
    # holder persists, and releases it shortly after.
    competing = sqlite3.connect(sys.argv[1], timeout=0.1, isolation_level=None,
                                check_same_thread=False)
    competing.execute('BEGIN IMMEDIATE')
    holders.append(competing)
    threading.Timer(0.15, competing.rollback).start()
    return httpx.Response(200, json={
        'access_token': 'new-access', 'refresh_token': 'new-refresh', 'expires_in': 3600,
    })

with respx.mock:
    respx.post(TOKEN_URI).mock(side_effect=token_endpoint)
    assert service.ensure_access_token(account) == 'new-access'
time.sleep(0.05)
holders[0].close()
row = WhoopAccount.objects.get(pk=account.pk)
assert row.get_refresh_token() == 'new-refresh'
"""))
