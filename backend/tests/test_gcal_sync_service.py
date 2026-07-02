"""Service-layer tests for ``gcal_sync.service``.

Mocks at the client boundary (``httpx.AsyncClient`` / ``httpx.Client`` /
``Flow``), NOT a network library, so tests are deterministic and offline —
the same pattern as ``test_calendar_sync_service.py`` (which patches
``caldav.DAVClient``). No ``respx`` dep is added.

Async functions are exercised via ``asyncio.run`` from sync tests (no
``pytest-asyncio`` dependency). The account fixture carries a *fresh* cached
access token so ``_ensure_access_token`` returns early without a refresh —
that keeps the events tests off the ``sync_to_async`` persist path and its
cross-thread DB connection.
"""

import asyncio
import datetime
import logging
from datetime import timedelta
from unittest.mock import MagicMock, patch

import google.auth.exceptions
import httpx
import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.utils import timezone as django_tz
from gcal_sync import service
from gcal_sync.models import GoogleCalendarAccount

FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def _gcal_settings(settings):
    settings.GOOGLE_OAUTH_TOKEN_KEY = FERNET_KEY
    settings.GOOGLE_OAUTH_CLIENT_ID = "client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "client-secret"
    settings.GOOGLE_OAUTH_REDIRECT_URI = "https://app.test/api/calendar/google/callback/"
    settings.GOOGLE_CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
    settings.GOOGLE_REQUEST_TIMEOUT = 5
    settings.GOOGLE_CACHE_TTL_SECONDS = 300
    settings.TIME_ZONE = "UTC"


@pytest.fixture
def account(db):
    user = User.objects.create_user(username="g-user", password="x")
    acc = GoogleCalendarAccount(
        user=user, google_account_id="sub-123", email="alice@gmail.com"
    )
    acc.set_refresh_token("refresh-abc")
    acc.set_access_token("access-xyz")
    acc.access_token_expiry = django_tz.now() + timedelta(hours=1)
    acc.save()
    return acc


# ----- fake httpx async client -------------------------------------------


class _FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


def _make_async_client(
    calendar_items,
    events_by_calendar,
    *,
    calendar_status=200,
    events_status=200,
    raise_exc=None,
):
    """Build a patchable ``httpx.AsyncClient`` factory.

    ``events_by_calendar`` is keyed by the *decoded* calendar id. ``.calls``
    records every requested URL (for the URL-encoding assertion).
    """
    calls: list[str] = []

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            calls.append(url)
            if raise_exc is not None:
                raise raise_exc
            if url.endswith("/calendarList"):
                return _FakeResponse(calendar_status, {"items": calendar_items})
            seg = url.split("/calendars/")[1].rsplit("/events", 1)[0]
            import urllib.parse as _up

            cal_id = _up.unquote(seg)
            return _FakeResponse(
                events_status, {"items": events_by_calendar.get(cal_id, [])}
            )

    def _factory(**kwargs):
        return _FakeAsyncClient()

    _factory.calls = calls
    return _factory


def _timed(eid, summary, start_iso, end_iso, status="confirmed"):
    return {
        "id": eid,
        "status": status,
        "summary": summary,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }


def _allday(eid, summary, start_date, end_date):
    return {
        "id": eid,
        "status": "confirmed",
        "summary": summary,
        "start": {"date": start_date},
        "end": {"date": end_date},
    }


# ----- exchange_code ------------------------------------------------------


class _FakeCredentials:
    def __init__(self, refresh_token="r-1", token="a-1", id_token="idtok"):
        self.refresh_token = refresh_token
        self.token = token
        self.expiry = datetime.datetime(2026, 5, 7, 13, 0, 0)  # naive UTC
        self.id_token = id_token


class TestExchangeCode:
    def test_returns_account_info(self, db):
        fake_flow = MagicMock()
        fake_flow.credentials = _FakeCredentials(refresh_token="r-1", token="a-1")
        with patch.object(service, "_build_flow", return_value=fake_flow), patch.object(
            service, "_verify_id_token",
            return_value={"sub": "sub-9", "email": "bob@gmail.com"},
        ), patch.object(service, "_fetch_calendar_list_sync", return_value=[]):
            info = service.exchange_code("the-code", "the-state")

        assert info["google_account_id"] == "sub-9"
        assert info["email"] == "bob@gmail.com"
        assert info["refresh_token"] == "r-1"
        assert info["access_token"] == "a-1"
        # expiry coerced to aware UTC.
        assert info["expiry"].tzinfo is not None
        fake_flow.fetch_token.assert_called_once()

    def test_missing_refresh_token_is_hard_error(self, db):
        fake_flow = MagicMock()
        fake_flow.credentials = _FakeCredentials(refresh_token=None)
        with patch.object(service, "_build_flow", return_value=fake_flow):
            with pytest.raises(service.GoogleCalAuthError):
                service.exchange_code("the-code", "the-state")

    def test_id_token_absent_falls_back_to_primary_calendar(self, db):
        fake_flow = MagicMock()
        fake_flow.credentials = _FakeCredentials(id_token=None)
        with patch.object(service, "_build_flow", return_value=fake_flow), patch.object(
            service,
            "_fetch_calendar_list_sync",
            return_value=[{"id": "me@gmail.com", "primary": True}],
        ):
            info = service.exchange_code("the-code", "the-state")
        assert info["google_account_id"] == "me@gmail.com"
        assert info["email"] == "me@gmail.com"


# ----- _refresh_sync / token lifecycle -----------------------------------


class TestTokenLifecycle:
    def test_refresh_sync_revoked_raises_auth(self, db):
        fake_creds = MagicMock()
        fake_creds.refresh.side_effect = google.auth.exceptions.RefreshError("revoked")
        with patch.object(
            service.google.oauth2.credentials, "Credentials", return_value=fake_creds
        ):
            with pytest.raises(service.GoogleCalAuthError):
                service._refresh_sync("refresh-abc")

    def test_refresh_sync_detects_rotation(self, db):
        fake_creds = MagicMock()
        fake_creds.token = "new-access"
        fake_creds.expiry = datetime.datetime(2026, 5, 7, 14, 0, 0)
        fake_creds.refresh_token = "rotated-refresh"  # differs from input
        fake_creds.refresh.return_value = None
        with patch.object(
            service.google.oauth2.credentials, "Credentials", return_value=fake_creds
        ):
            access, expiry, rotated = service._refresh_sync("refresh-abc")
        assert access == "new-access"
        assert rotated == "rotated-refresh"
        assert expiry.tzinfo is not None

    def test_refresh_sync_no_rotation_returns_none(self, db):
        fake_creds = MagicMock()
        fake_creds.token = "new-access"
        fake_creds.expiry = datetime.datetime(2026, 5, 7, 14, 0, 0)
        fake_creds.refresh_token = "refresh-abc"  # unchanged
        fake_creds.refresh.return_value = None
        with patch.object(
            service.google.oauth2.credentials, "Credentials", return_value=fake_creds
        ):
            _, _, rotated = service._refresh_sync("refresh-abc")
        assert rotated is None

    def test_persist_writes_when_expired(self, account):
        account.access_token_expiry = django_tz.now() - timedelta(minutes=1)
        account.save()
        old_updated = account.updated_at
        new_expiry = django_tz.now() + timedelta(hours=2)
        returned, updated_at = service._persist_refreshed_tokens(
            account.pk, "fresh-access", new_expiry, None
        )
        account.refresh_from_db()
        assert returned == "fresh-access"
        assert account.get_access_token() == "fresh-access"
        assert account.updated_at > old_updated  # auto_now → cache version rotates
        assert updated_at == account.updated_at  # post-refresh version returned

    def test_persist_skips_redundant_write_when_fresh_no_rotation(self, account):
        # account is fresh (expiry +1h) with access "access-xyz".
        old_updated = account.updated_at
        returned, updated_at = service._persist_refreshed_tokens(
            account.pk, "should-be-ignored", django_tz.now() + timedelta(hours=2), None
        )
        account.refresh_from_db()
        # Double-check skip: another caller already refreshed → reuse + no write.
        assert returned == "access-xyz"
        assert account.get_access_token() == "access-xyz"
        assert account.updated_at == old_updated
        assert updated_at == old_updated  # unchanged version returned

    def test_persist_rotated_refresh_even_when_fresh(self, account):
        # P1 lost-update guard: a caller holding a rotated refresh token MUST
        # persist it even when the access token is already fresh.
        old_updated = account.updated_at
        returned, _updated = service._persist_refreshed_tokens(
            account.pk,
            "new-access",
            django_tz.now() + timedelta(hours=2),
            "rotated-refresh",
        )
        account.refresh_from_db()
        assert account.get_refresh_token() == "rotated-refresh"
        assert account.get_access_token() == "new-access"
        assert returned == "new-access"
        assert account.updated_at > old_updated

    def test_concurrent_rotation_lost_update_guard(self, account):
        """Two refreshers of the same expired account, one with a rotated
        token: the rotated refresh token must be the persisted one and no
        stale token survives. (Persisted-token correctness, not call count.)
        """
        account.access_token_expiry = django_tz.now() - timedelta(minutes=1)
        account.save()
        # First refresher persists a normal (non-rotated) result.
        service._persist_refreshed_tokens(
            account.pk, "access-1", django_tz.now() + timedelta(hours=1), None
        )
        # Second refresher arrives with a rotated refresh token; the row is
        # now fresh, but rotation must NOT be discarded.
        service._persist_refreshed_tokens(
            account.pk, "access-2", django_tz.now() + timedelta(hours=1), "rotated-2"
        )
        account.refresh_from_db()
        assert account.get_refresh_token() == "rotated-2"

    def test_ensure_access_token_cache_reuse_skips_refresh(self, account):
        refresh_mock = MagicMock()
        with patch.object(service, "_refresh_sync", refresh_mock):
            token = asyncio.run(service._ensure_access_token(account))
        assert token == "access-xyz"
        refresh_mock.assert_not_called()

    def test_ensure_access_token_propagates_version_to_in_memory_account(self, account):
        # After a refresh, the post-refresh updated_at must be copied onto the
        # in-memory account so the caller's later set_cached_events keys on the
        # rotated (post-refresh) version, not the dead pre-refresh one.
        account.access_token_expiry = django_tz.now() - timedelta(minutes=1)
        account.save()
        new_updated = django_tz.now() + timedelta(minutes=5)
        with patch.object(
            service,
            "_refresh_sync",
            return_value=("tok", django_tz.now() + timedelta(hours=1), None),
        ), patch.object(
            service, "_persist_refreshed_tokens", return_value=("tok", new_updated)
        ):
            token = asyncio.run(service._ensure_access_token(account))
        assert token == "tok"
        assert account.updated_at == new_updated


class TestScopeRelaxation:
    def test_relax_token_scope_env_is_set(self):
        # Belt-and-suspenders: importing the service module sets the oauthlib
        # relax flag so a superset returned scope on re-consent doesn't crash
        # fetch_token.
        import os

        assert os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE") == "1"

    def test_authorization_url_omits_include_granted_scopes(self, db):
        # Incremental auth is intentionally NOT enabled (it would widen the
        # returned scope set and trip oauthlib's equality check).
        url = service.build_authorization_url("the-state")
        assert "include_granted_scopes" not in url

    def test_authorization_url_has_no_pkce_challenge(self, db):
        # PKCE is disabled — a stateless Flow rebuild at callback time can't
        # supply the code_verifier, so sending a code_challenge would fail the
        # token exchange with "Missing code verifier".
        url = service.build_authorization_url("the-state")
        assert "code_challenge" not in url

    def test_build_flow_disables_code_verifier(self, db):
        # Regression guard: if PKCE is ever re-enabled, the stateless Flow
        # rebuild at callback time loses the code_verifier and EVERY
        # production Google connect fails with "invalid_grant: Missing code
        # verifier". Keep the verifier off unless the session persists it.
        flow = service._build_flow("the-state")
        assert flow.autogenerate_code_verifier is False
        assert flow.code_verifier is None


# ----- fetch_events_for_account ------------------------------------------


class TestFetchEvents:
    _DATE = datetime.date(2026, 5, 7)

    def test_empty_day_returns_empty(self, account):
        factory = _make_async_client(
            [{"id": "primary", "summary": "Primary", "selected": True}], {}
        )
        with patch.object(service.httpx, "AsyncClient", factory):
            events = asyncio.run(service.fetch_events_for_account(account, self._DATE))
        assert events == []

    def test_multi_calendar_merge_and_normalisation(self, account):
        cals = [
            {"id": "primary", "summary": "Primary", "selected": True},
            {"id": "work", "summary": "Work", "selected": True},
            {"id": "ignored", "summary": "Ignored", "selected": False},
        ]
        events_by_cal = {
            "primary": [
                _timed("e1", "Lunch", "2026-05-07T14:00:00+00:00",
                       "2026-05-07T15:00:00+00:00"),
                _allday("e2", "Conference", "2026-05-07", "2026-05-08"),
            ],
            # IANA-offset event → must convert to UTC (16:00+02:00 == 14:00Z).
            "work": [
                _timed("e3", "Standup", "2026-05-07T16:00:00+02:00",
                       "2026-05-07T16:30:00+02:00"),
            ],
            "ignored": [_timed("e4", "Hidden", "2026-05-07T10:00:00+00:00",
                               "2026-05-07T11:00:00+00:00")],
        }
        factory = _make_async_client(cals, events_by_cal)
        with patch.object(service.httpx, "AsyncClient", factory):
            events = asyncio.run(service.fetch_events_for_account(account, self._DATE))

        titles = [e.title for e in events]
        assert "Hidden" not in titles  # non-selected calendar excluded
        assert set(titles) == {"Conference", "Lunch", "Standup"}
        # Sorted by (start, title, uid): all-day 00:00Z first, then 14:00Z pair.
        assert events[0].title == "Conference"
        assert events[0].all_day is True
        # Standup converted from +02:00 to 14:00Z.
        standup = next(e for e in events if e.title == "Standup")
        assert standup.start.hour == 14
        assert standup.start.tzinfo == datetime.UTC
        # account_label carries the email; external_uid namespaced.
        assert all(e.account_label == "alice@gmail.com" for e in events)
        assert all(e.external_uid.endswith("@google") for e in events)

    def test_cancelled_event_skipped(self, account):
        cals = [{"id": "primary", "summary": "Primary", "selected": True}]
        events_by_cal = {
            "primary": [
                _timed("e1", "Real", "2026-05-07T09:00:00+00:00",
                       "2026-05-07T10:00:00+00:00"),
                {"id": "e2", "status": "cancelled", "start": {}, "end": {}},
            ]
        }
        factory = _make_async_client(cals, events_by_cal)
        with patch.object(service.httpx, "AsyncClient", factory):
            events = asyncio.run(service.fetch_events_for_account(account, self._DATE))
        assert [e.title for e in events] == ["Real"]

    def test_calendar_id_is_url_encoded(self, account):
        # Cover BOTH '@' (shared-calendar ids) AND '#' (would otherwise start a
        # URL fragment and truncate the path).
        cal_id = "a#b@group.calendar.google.com"
        cals = [{"id": cal_id, "summary": "Team", "selected": True}]
        factory = _make_async_client(cals, {cal_id: []})
        with patch.object(service.httpx, "AsyncClient", factory):
            asyncio.run(service.fetch_events_for_account(account, self._DATE))
        event_calls = [u for u in factory.calls if "/events" in u]
        assert event_calls, "expected an events request"
        # @ → %40, # → %23; neither raw char may survive in the path.
        assert all("%40group.calendar.google.com" in u for u in event_calls)
        assert all("%23" in u for u in event_calls)
        assert all("#" not in u and "@" not in u for u in event_calls)

    def test_timeout_maps_to_timeout_error(self, account):
        cals = [{"id": "primary", "summary": "Primary", "selected": True}]
        factory = _make_async_client(
            cals, {}, raise_exc=httpx.TimeoutException("slow")
        )
        with patch.object(service.httpx, "AsyncClient", factory):
            with pytest.raises(service.GoogleCalTimeoutError):
                asyncio.run(service.fetch_events_for_account(account, self._DATE))

    def test_provider_500_maps_to_provider_error(self, account):
        cals = [{"id": "primary", "summary": "Primary", "selected": True}]
        factory = _make_async_client(cals, {}, calendar_status=500)
        with patch.object(service.httpx, "AsyncClient", factory):
            with pytest.raises(service.GoogleCalProviderError):
                asyncio.run(service.fetch_events_for_account(account, self._DATE))

    def test_revoked_401_maps_to_auth_error(self, account):
        cals = [{"id": "primary", "summary": "Primary", "selected": True}]
        factory = _make_async_client(cals, {}, calendar_status=401)
        with patch.object(service.httpx, "AsyncClient", factory):
            with pytest.raises(service.GoogleCalAuthError):
                asyncio.run(service.fetch_events_for_account(account, self._DATE))


def _make_paging_client(event_pages, *, endless=False):
    """Fake AsyncClient whose events endpoint paginates via nextPageToken.

    ``event_pages`` is a list of per-page item lists. With ``endless=True`` the
    events endpoint always returns a nextPageToken (exercises the _MAX_PAGES
    overflow guard).
    """
    calls: list = []

    class _Resp:
        def __init__(self, status, data):
            self.status_code = status
            self._data = data

        def json(self):
            return self._data

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            calls.append((url, dict(params or {})))
            if url.endswith("/calendarList"):
                return _Resp(
                    200,
                    {"items": [{"id": "primary", "summary": "Primary", "selected": True}]},
                )
            if endless:
                return _Resp(200, {"items": [], "nextPageToken": "more"})
            token = (params or {}).get("pageToken")
            idx = 0 if token is None else int(token)
            data = {"items": event_pages[idx]}
            if idx + 1 < len(event_pages):
                data["nextPageToken"] = str(idx + 1)
            return _Resp(200, data)

    def _factory(**kwargs):
        return _Client()

    _factory.calls = calls
    return _factory


class TestNormalisationEdgeCases:
    _DATE = datetime.date(2026, 5, 7)

    def test_all_day_event_utc_window(self, account):
        cals = [{"id": "primary", "summary": "Primary", "selected": True}]
        factory = _make_async_client(
            cals, {"primary": [_allday("e2", "Conf", "2026-05-07", "2026-05-08")]}
        )
        with patch.object(service.httpx, "AsyncClient", factory):
            events = asyncio.run(service.fetch_events_for_account(account, self._DATE))
        assert len(events) == 1
        ev = events[0]
        assert ev.all_day is True
        # TIME_ZONE=UTC: midnight UTC, exclusive end kept as +1 day.
        assert ev.start == datetime.datetime(2026, 5, 7, 0, 0, tzinfo=datetime.UTC)
        assert ev.end == datetime.datetime(2026, 5, 8, 0, 0, tzinfo=datetime.UTC)

    def test_all_day_event_non_utc_timezone(self, account, settings):
        # All-day window must synthesize midnight in settings.TIME_ZONE, then
        # convert to UTC — proves _date_to_utc's TZ math (not a no-op under UTC).
        settings.TIME_ZONE = "America/New_York"  # EDT = UTC-4 in May
        cals = [{"id": "primary", "summary": "Primary", "selected": True}]
        factory = _make_async_client(
            cals, {"primary": [_allday("e2", "Conf", "2026-05-07", "2026-05-08")]}
        )
        with patch.object(service.httpx, "AsyncClient", factory):
            events = asyncio.run(service.fetch_events_for_account(account, self._DATE))
        ev = events[0]
        # Midnight EDT 2026-05-07 == 04:00 UTC.
        assert ev.start == datetime.datetime(2026, 5, 7, 4, 0, tzinfo=datetime.UTC)
        assert ev.end == datetime.datetime(2026, 5, 8, 4, 0, tzinfo=datetime.UTC)

    def test_out_of_window_event_dropped(self, account):
        # The defensive window guard drops an event the (fake) provider
        # returned outside [start, end) — guards against an inverted filter.
        cals = [{"id": "primary", "summary": "Primary", "selected": True}]
        factory = _make_async_client(
            cals,
            {
                "primary": [
                    _timed("prev", "PrevDay", "2026-05-06T09:00:00+00:00",
                           "2026-05-06T10:00:00+00:00"),
                    _timed("ok", "InWindow", "2026-05-07T09:00:00+00:00",
                           "2026-05-07T10:00:00+00:00"),
                ]
            },
        )
        with patch.object(service.httpx, "AsyncClient", factory):
            events = asyncio.run(service.fetch_events_for_account(account, self._DATE))
        assert [e.title for e in events] == ["InWindow"]


class TestPagination:
    _DATE = datetime.date(2026, 5, 7)

    def test_events_pages_are_merged(self, account):
        pages = [
            [_timed("e1", "First", "2026-05-07T09:00:00+00:00",
                    "2026-05-07T10:00:00+00:00")],
            [_timed("e2", "Second", "2026-05-07T11:00:00+00:00",
                    "2026-05-07T12:00:00+00:00")],
        ]
        factory = _make_paging_client(pages)
        with patch.object(service.httpx, "AsyncClient", factory):
            events = asyncio.run(service.fetch_events_for_account(account, self._DATE))
        assert {e.title for e in events} == {"First", "Second"}
        # The second page was requested with a pageToken.
        assert any("pageToken" in p for _, p in factory.calls)

    def test_endless_pagination_raises_provider_error(self, account):
        factory = _make_paging_client([], endless=True)
        with patch.object(service.httpx, "AsyncClient", factory):
            with pytest.raises(service.GoogleCalProviderError):
                asyncio.run(service.fetch_events_for_account(account, self._DATE))


class TestCredentialsNeverLogged:
    def test_tokens_never_appear_in_logs(self, account, caplog):
        cals = [{"id": "primary", "summary": "Primary", "selected": True}]
        events_by_cal = {
            "primary": [
                _timed("e1", "Real", "2026-05-07T09:00:00+00:00",
                       "2026-05-07T10:00:00+00:00"),
                # malformed event → triggers the warning log path
                {"id": "bad", "status": "confirmed", "start": {}, "end": {}},
            ]
        }
        factory = _make_async_client(cals, events_by_cal)
        with caplog.at_level(logging.DEBUG):
            with patch.object(service.httpx, "AsyncClient", factory):
                asyncio.run(
                    service.fetch_events_for_account(account, datetime.date(2026, 5, 7))
                )
            # exchange path with a code that must never be logged
            fake_flow = MagicMock()
            fake_flow.credentials = _FakeCredentials()
            with patch.object(service, "_build_flow", return_value=fake_flow), patch.object(
                service, "_verify_id_token",
                return_value={"sub": "s", "email": "e@e.com"},
            ), patch.object(service, "_fetch_calendar_list_sync", return_value=[]):
                service.exchange_code("super-secret-code", "state")

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "refresh-abc" not in joined
        assert "access-xyz" not in joined
        assert "super-secret-code" not in joined
        # ciphertext defence-in-depth — both refresh AND access token hex.
        assert bytes(account.refresh_token_encrypted).hex() not in joined
        assert bytes(account.access_token_encrypted).hex() not in joined
