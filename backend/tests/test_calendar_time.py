"""Saved-timezone day windows and calendar date-only values."""

import datetime
from types import SimpleNamespace

import icalendar
import pytest
from calendar_sync import cache as caldav_cache
from calendar_sync import service as caldav_service
from calendar_sync.schemas import normalized_event_to_dict
from calendar_sync.time import floating_datetime_to_utc, local_day_bounds_utc
from gcal_sync import cache as google_cache
from gcal_sync import service as google_service


@pytest.mark.parametrize(
    ("time_zone", "date", "start", "end"),
    [
        ("UTC", "2026-05-07", "2026-05-07T00:00:00+00:00", "2026-05-08T00:00:00+00:00"),
        ("Asia/Qatar", "2026-05-07", "2026-05-06T21:00:00+00:00", "2026-05-07T21:00:00+00:00"),
        (
            "America/New_York",
            "2026-05-07",
            "2026-05-07T04:00:00+00:00",
            "2026-05-08T04:00:00+00:00",
        ),
        ("Asia/Kathmandu", "2026-05-07", "2026-05-06T18:15:00+00:00", "2026-05-07T18:15:00+00:00"),
        (
            "America/New_York",
            "2026-03-08",
            "2026-03-08T05:00:00+00:00",
            "2026-03-09T04:00:00+00:00",
        ),
        (
            "America/New_York",
            "2026-11-01",
            "2026-11-01T04:00:00+00:00",
            "2026-11-02T05:00:00+00:00",
        ),
    ],
)
def test_local_day_bounds_cover_entire_day(time_zone, date, start, end):
    target = datetime.date.fromisoformat(date)
    expected = tuple(datetime.datetime.fromisoformat(value) for value in (start, end))
    assert local_day_bounds_utc(target, time_zone) == expected
    assert caldav_service._day_window(target, time_zone) == expected
    assert google_service._day_window(target, time_zone) == expected


def test_naive_caldav_time_uses_saved_timezone():
    floating = datetime.datetime(2026, 5, 7, 0, 30)
    assert floating_datetime_to_utc(floating, "Asia/Qatar") == datetime.datetime(
        2026, 5, 6, 21, 30, tzinfo=datetime.UTC
    )
    # An explicit offset in the event remains authoritative.
    aware = datetime.datetime(2026, 5, 7, 0, 30, tzinfo=datetime.UTC)
    assert floating_datetime_to_utc(aware, "Asia/Qatar") == aware


def test_repeated_floating_hour_uses_first_occurrence_without_fold():
    repeated = datetime.datetime(2026, 11, 1, 1, 30)
    assert floating_datetime_to_utc(repeated, "America/New_York") == (
        datetime.datetime(2026, 11, 1, 5, 30, tzinfo=datetime.UTC)
    )
    assert floating_datetime_to_utc(
        repeated.replace(fold=1), "America/New_York"
    ) == datetime.datetime(2026, 11, 1, 6, 30, tzinfo=datetime.UTC)


def test_all_day_date_stays_on_its_calendar_day_across_utc_midnight():
    cal = icalendar.Calendar.from_ical(
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\n"
        "UID:date-1\nDTSTART;VALUE=DATE:20260507\n"
        "DTEND;VALUE=DATE:20260508\nEND:VEVENT\nEND:VCALENDAR"
    )
    vevent = next(item for item in cal.walk() if item.name == "VEVENT")
    apple = caldav_service._normalize_vevent(vevent, "Personal", "Asia/Qatar")
    google = google_service._normalize_gcal_event(
        {"id": "date-1", "start": {"date": "2026-05-07"}, "end": {"date": "2026-05-08"}},
        "Personal",
        "alice@example.com",
        "Asia/Qatar",
    )
    for event in (apple, google):
        assert event is not None
        wire = normalized_event_to_dict(event)
        assert wire["start"] == "2026-05-06T21:00:00+00:00"
        assert wire["start_date"] == "2026-05-07"
        assert wire["end_date"] == "2026-05-08"


def test_cross_midnight_event_overlaps_local_day():
    # 22:30 UTC on May 6 is 01:30 on May 7 in Qatar.
    start, end = local_day_bounds_utc(datetime.date(2026, 5, 7), "Asia/Qatar")
    event_start = datetime.datetime(2026, 5, 6, 22, 30, tzinfo=datetime.UTC)
    event_end = datetime.datetime(2026, 5, 7, 0, 30, tzinfo=datetime.UTC)
    assert event_start < end and event_end > start


def test_google_timed_value_without_offset_uses_explicit_or_viewer_zone():
    base = {
        "id": "floating",
        "start": {"dateTime": "2026-05-07T09:00:00"},
        "end": {"dateTime": "2026-05-07T10:00:00"},
    }
    viewer = google_service._normalize_gcal_event(base, "Work", "alice@example.com", "Asia/Qatar")
    assert viewer is not None
    assert viewer.start == datetime.datetime(2026, 5, 7, 6, tzinfo=datetime.UTC)

    explicit = {
        **base,
        "start": {**base["start"], "timeZone": "America/New_York"},
        "end": {**base["end"], "timeZone": "America/New_York"},
    }
    provider = google_service._normalize_gcal_event(
        explicit, "Work", "alice@example.com", "Asia/Qatar"
    )
    assert provider is not None
    assert provider.start == datetime.datetime(2026, 5, 7, 13, tzinfo=datetime.UTC)


def test_calendar_caches_separate_timezones_and_old_key_namespace():
    account = SimpleNamespace(
        user_id=7,
        id=13,
        updated_at=datetime.datetime(2026, 5, 7, tzinfo=datetime.UTC),
    )
    target = datetime.date(2026, 5, 7)
    for module, old_prefix in ((caldav_cache, "caldav_events:"), (google_cache, "gcal_events:")):
        utc_key = module.events_cache_key(account, target, "UTC")
        qatar_key = module.events_cache_key(account, target, "Asia/Qatar")
        assert utc_key != qatar_key
        assert utc_key.startswith(f"{old_prefix}v2:")
