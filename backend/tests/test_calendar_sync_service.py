"""Service-layer tests for ``calendar_sync.service``.

Mock the ``caldav.DAVClient`` at the boundary (not the HTTP layer) so
tests are deterministic and offline. Cover the four acceptance-criteria
scenarios plus the recurrence path and the no-plaintext-in-logs check.
"""

import datetime
import logging
from unittest.mock import MagicMock, patch

import caldav
import pytest
from caldav.lib.error import AuthorizationError, DAVError
from calendar_sync import service
from calendar_sync.models import CalDAVAccount
from cryptography.fernet import Fernet
from django.contrib.auth.models import User

FERNET_KEY = Fernet.generate_key().decode()

VEVENT_TIMED = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:timed-001@example.com
DTSTAMP:20260507T000000Z
DTSTART:20260507T140000Z
DTEND:20260507T150000Z
SUMMARY:Lunch with Pat
END:VEVENT
END:VCALENDAR
"""

VEVENT_ALL_DAY = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:allday-001@example.com
DTSTAMP:20260507T000000Z
DTSTART;VALUE=DATE:20260507
DTEND;VALUE=DATE:20260508
SUMMARY:Conference
END:VEVENT
END:VCALENDAR
"""

VEVENT_RRULE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
UID:rrule-001@example.com
DTSTAMP:20260501T000000Z
DTSTART:20260501T090000Z
DTEND:20260501T093000Z
SUMMARY:Daily standup
RRULE:FREQ=DAILY;COUNT=20
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture(autouse=True)
def _fernet_key(settings):
    settings.CALDAV_ENCRYPTION_KEY = FERNET_KEY
    settings.CALDAV_REQUEST_TIMEOUT = 5
    settings.CALDAV_CACHE_TTL_SECONDS = 300


def _caldav_event(data: str) -> caldav.Event:
    return caldav.Event(client=None, data=data)


def _build_fake_principal(calendars):
    principal = MagicMock()
    principal.calendars.return_value = calendars
    return principal


def _build_fake_calendar(name, events_returned, *, search_raises=None):
    cal = MagicMock()
    cal.name = name
    if search_raises is not None:
        cal.date_search.side_effect = search_raises
    else:
        cal.date_search.return_value = events_returned
    return cal


@pytest.fixture
def account(db):
    user = User.objects.create_user(username="cal-user", password="x")
    acc = CalDAVAccount(
        user=user,
        apple_id="alice@example.com",
        base_url="https://caldav.icloud.com/",
    )
    acc.set_password("hunter2-app-specific")
    acc.save()
    return acc


@pytest.fixture
def patched_dav_client():
    """Patch ``caldav.DAVClient`` used by ``service``."""
    with patch("calendar_sync.service.caldav.DAVClient") as cls:
        instance = MagicMock()
        cls.return_value = instance
        yield instance


class TestFetchEventsForDate:
    def test_fetch_success_normalises_timed_and_allday(self, account, patched_dav_client):
        cal = _build_fake_calendar(
            "Personal",
            [_caldav_event(VEVENT_TIMED), _caldav_event(VEVENT_ALL_DAY)],
        )
        patched_dav_client.principal.return_value = _build_fake_principal([cal])

        events = service.fetch_events_for_date(account, datetime.date(2026, 5, 7))

        assert len(events) == 2
        # Sorted by start ascending; all-day starts at 00:00 UTC,
        # timed at 14:00 UTC.
        assert events[0].title == "Conference"
        assert events[0].all_day is True
        assert events[1].title == "Lunch with Pat"
        assert events[1].all_day is False
        assert events[1].calendar_name == "Personal"

    def test_fetch_invalid_credentials_raises_auth(self, account, patched_dav_client):
        patched_dav_client.principal.side_effect = AuthorizationError()
        with pytest.raises(service.CalDAVAuthError):
            service.fetch_events_for_date(account, datetime.date(2026, 5, 7))

    def test_fetch_empty_day_returns_empty_list(self, account, patched_dav_client):
        cal = _build_fake_calendar("Personal", [])
        patched_dav_client.principal.return_value = _build_fake_principal([cal])
        assert service.fetch_events_for_date(account, datetime.date(2026, 5, 7)) == []

    def test_fetch_provider_failure_raises_provider(self, account, patched_dav_client):
        patched_dav_client.principal.side_effect = DAVError("boom")
        with pytest.raises(service.CalDAVProviderError):
            service.fetch_events_for_date(account, datetime.date(2026, 5, 7))

    def test_fetch_timeout_raises_timeout(self, account, patched_dav_client):
        patched_dav_client.principal.side_effect = TimeoutError("timed out")
        with pytest.raises(service.CalDAVTimeoutError):
            service.fetch_events_for_date(account, datetime.date(2026, 5, 7))

    def test_malformed_vevent_is_skipped_not_crash(self, caplog):
        """A VEVENT with a missing required field (e.g. DTSTART) must be
        skipped (logged warning) rather than crashing the whole fetch
        (review iter-3 P2 TESTING). Direct unit-level test on
        ``_normalize_vevent`` — narrow catch list returns None for the
        documented error types.
        """
        # Build a real Calendar with a VEVENT, then drop DTSTART.
        import icalendar
        cal = icalendar.Calendar.from_ical(VEVENT_TIMED)
        vevent = next(c for c in cal.walk() if c.name == "VEVENT")
        del vevent["DTSTART"]

        with caplog.at_level(logging.WARNING):
            result = service._normalize_vevent(vevent, "TestCal")

        assert result is None
        assert any(
            "Failed to normalize VEVENT" in r.getMessage()
            for r in caplog.records
        )
        # Type name appears in the warning so ops can identify recurring
        # data-quality issues.
        assert any("KeyError" in r.getMessage() for r in caplog.records)

    def test_fetch_per_calendar_dav_error_propagates(self, account, patched_dav_client):
        """A DAVError raised by ``calendar.date_search`` MUST propagate
        as a CalDAVProviderError — silently skipping the calendar would
        hide a real provider failure (review finding, 0011_REVIEW.md)."""
        cal = MagicMock()
        cal.name = "Personal"
        cal.date_search.side_effect = DAVError("dav broke on this calendar")
        patched_dav_client.principal.return_value = _build_fake_principal([cal])

        with pytest.raises(service.CalDAVProviderError):
            service.fetch_events_for_date(account, datetime.date(2026, 5, 7))

    def test_recurring_event_expansion_single_day(self, account, patched_dav_client):
        cal = _build_fake_calendar("Work", [_caldav_event(VEVENT_RRULE)])
        patched_dav_client.principal.return_value = _build_fake_principal([cal])

        events = service.fetch_events_for_date(account, datetime.date(2026, 5, 3))

        assert len(events) == 1
        ev = events[0]
        assert ev.title == "Daily standup"
        # external_uid must contain RECURRENCE-ID per the plan.
        assert "rrule-001@example.com" in ev.external_uid
        assert "#" in ev.external_uid


class TestCredentialsNeverLogged:
    """Test #11 from the plan: ``test_credentials_never_logged``."""

    def test_password_never_appears_in_logs(self, account, patched_dav_client, caplog):
        password_plain = "hunter2-app-specific"
        # Success path
        cal = _build_fake_calendar("X", [])
        patched_dav_client.principal.return_value = _build_fake_principal([cal])
        with caplog.at_level(logging.DEBUG):
            service.fetch_events_for_date(account, datetime.date(2026, 5, 7))
        # Failure path
        patched_dav_client.principal.side_effect = DAVError("boom")
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(service.CalDAVProviderError):
                service.fetch_events_for_date(account, datetime.date(2026, 5, 7))

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert password_plain not in joined
