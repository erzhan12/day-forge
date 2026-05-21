"""Phase 0 spike: pin the canonical accessor for caldav.Event → icalendar.

The CalDAV integration plan (`docs/features/0011_caldav_apple_calendar_PLAN.md`,
Phase 0) requires committing one canonical parse path before service-layer
work begins. The two candidates were:

  - ``event.icalendar_instance`` — returns an ``icalendar.Calendar``
    directly (preferred — no re-parse, uses the lib's cached parse).
  - ``icalendar.Calendar.from_ical(event.data)`` — re-parses from the raw
    text on every call.

Both feed ``recurring_ical_events.of(...).between(start, end)`` equivalently,
but ``icalendar_instance`` is the documented accessor on
``caldav.calendarobjectresource.CalendarObjectResource`` and avoids the
duplicate parse, so it's the pin.

A future caldav-lib version that renames or removes ``icalendar_instance``
must surface as a test failure here, not as a silent fallback that adds
parse-cost per fetch.
"""

from datetime import UTC, datetime

import caldav
import icalendar
import recurring_ical_events

VEVENT_RRULE = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Day Forge Test//EN
BEGIN:VEVENT
UID:spike-rrule-001@example.com
DTSTAMP:20260101T000000Z
DTSTART:20260101T090000Z
DTEND:20260101T100000Z
SUMMARY:Daily standup
RRULE:FREQ=DAILY;COUNT=10
END:VEVENT
END:VCALENDAR
"""


def _build_caldav_event() -> caldav.Event:
    """Stand-in for a server-returned ``caldav.Event`` — no network call.

    ``caldav.Event(client=None, data=...)`` runs the same vcal.fix +
    icalendar parse pipeline that a real DAV ``GET`` response goes
    through, so the accessor surface is identical.
    """
    return caldav.Event(client=None, data=VEVENT_RRULE)


def test_icalendar_instance_is_a_calendar():
    event = _build_caldav_event()
    inst = event.icalendar_instance
    assert isinstance(inst, icalendar.Calendar)


def test_recurring_expansion_via_icalendar_instance():
    """Pinned accessor: ``event.icalendar_instance`` → ``recurring_ical_events.of``."""
    event = _build_caldav_event()
    start = datetime(2026, 1, 3, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 1, 4, 0, 0, 0, tzinfo=UTC)

    expanded = recurring_ical_events.of(event.icalendar_instance).between(start, end)

    assert len(expanded) == 1
    assert str(expanded[0]["SUMMARY"]) == "Daily standup"
    assert expanded[0]["DTSTART"].dt == datetime(2026, 1, 3, 9, 0, tzinfo=UTC)


def test_recurring_expansion_returns_empty_outside_window():
    """A window with no RRULE occurrence yields ``[]`` — defensive check
    that the upstream library does not silently emit the master event."""
    event = _build_caldav_event()
    # RRULE is COUNT=10 starting 2026-01-01; ask for a date well past
    # the final occurrence (2026-01-10).
    start = datetime(2026, 2, 1, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 2, 2, 0, 0, 0, tzinfo=UTC)

    expanded = recurring_ical_events.of(event.icalendar_instance).between(start, end)

    assert expanded == []
