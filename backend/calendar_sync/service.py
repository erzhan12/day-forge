"""CalDAV client wrapper for the calendar_sync app.

**Service-boundary owns the secret.** ``fetch_events_for_date`` is the
ONLY function that calls ``account.get_password()``. Views pass the
``CalDAVAccount`` instance through; they never touch the plaintext. This
keeps the decryption surface to a single file and makes the
"credentials never logged" test (#11) tractable.
"""

import datetime
import logging
from collections.abc import Iterable
from datetime import date
from datetime import datetime as dt

import caldav
import recurring_ical_events
from caldav.lib.error import AuthorizationError, DAVError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as django_tz

try:  # ``requests`` is a transitive caldav dep, but be defensive
    from requests.exceptions import Timeout as _RequestsTimeout
    _TIMEOUT_EXC: tuple[type[BaseException], ...] = (TimeoutError, _RequestsTimeout)
except Exception:  # pragma: no cover
    _TIMEOUT_EXC = (TimeoutError,)

from calendar_sync.schemas import NormalizedEvent

logger = logging.getLogger(__name__)


# ----- Typed exception hierarchy -----------------------------------------

class CalDAVError(Exception):
    """Base for all CalDAV service-layer errors."""


class CalDAVAuthError(CalDAVError):
    """Apple rejected the credentials (401/403 from DAV)."""


class CalDAVTimeoutError(CalDAVError):
    """Network timeout to iCloud."""


class CalDAVProviderError(CalDAVError):
    """Anything else from the DAV layer — wrap to keep views simple."""


# ----- verify_credentials ------------------------------------------------

def verify_credentials(apple_id: str, password: str, base_url: str) -> None:
    """Open a DAV client and prove the credentials work.

    Raises a typed ``CalDAVError`` subclass on failure; returns ``None``
    on success. Never logs the password.
    """
    try:
        client = caldav.DAVClient(
            url=base_url,
            username=apple_id,
            password=password,
            timeout=settings.CALDAV_REQUEST_TIMEOUT,
        )
        principal = client.principal()
        # Listing calendars hits a second DAV endpoint — without this
        # iCloud's ``principal()`` returns even when the password is
        # only partially valid for some endpoints.
        list(principal.calendars())
    except AuthorizationError as e:
        raise CalDAVAuthError("CalDAV authentication failed") from e
    except _TIMEOUT_EXC as e:
        raise CalDAVTimeoutError("CalDAV request timed out") from e
    except DAVError as e:
        raise CalDAVProviderError("CalDAV provider error") from e
    except Exception as e:  # pragma: no cover - defensive
        raise CalDAVProviderError("CalDAV provider error") from e


# ----- fetch_events_for_date ---------------------------------------------

def _day_window(target_date: date) -> tuple[dt, dt]:
    """``[start, end)`` in the project timezone, then handed to DAV.

    V1 uses ``settings.TIME_ZONE`` (per-user TZ isn't stored). We pass
    aware datetimes to ``date_search`` and to
    ``recurring_ical_events.of(...).between``; both libraries accept
    aware inputs.
    """
    tz = django_tz.get_current_timezone()
    start = dt.combine(target_date, datetime.time.min, tzinfo=tz)
    end = start + datetime.timedelta(days=1)
    return start, end


def _to_utc(value):
    """Promote naive datetimes to settings.TIME_ZONE, then convert to UTC."""
    if isinstance(value, dt):
        if django_tz.is_naive(value):
            value = django_tz.make_aware(
                value, django_tz.get_current_timezone()
            )
        return value.astimezone(datetime.UTC)
    # ``date`` (all-day) — synthesize midnight in project TZ then UTC.
    naive = dt.combine(value, datetime.time.min)
    aware = django_tz.make_aware(naive, django_tz.get_current_timezone())
    return aware.astimezone(datetime.UTC)


def _is_all_day(dtstart_value) -> bool:
    """All-day events have ``date`` (not ``datetime``) DTSTART per RFC 5545."""
    return isinstance(dtstart_value, date) and not isinstance(dtstart_value, dt)


def _normalize_vevent(vevent, calendar_name: str) -> NormalizedEvent | None:
    """Build a NormalizedEvent from one expanded VEVENT; return None on
    malformed input rather than crashing the whole fetch."""
    try:
        dtstart = vevent["DTSTART"].dt
        # DTEND is optional in RFC 5545; fall back to DURATION or +1h.
        if "DTEND" in vevent:
            dtend = vevent["DTEND"].dt
        elif "DURATION" in vevent:
            dtend_native = dtstart + vevent["DURATION"].dt
            dtend = dtend_native
        else:
            dtend = (
                dtstart + datetime.timedelta(days=1)
                if _is_all_day(dtstart)
                else dtstart + datetime.timedelta(hours=1)
            )
        all_day = _is_all_day(dtstart)
        start_utc = _to_utc(dtstart)
        end_utc = _to_utc(dtend)
        uid = str(vevent.get("UID", ""))
        # Per the plan: include RECURRENCE-ID so each occurrence is unique.
        recurrence_id = vevent.get("RECURRENCE-ID")
        if recurrence_id is not None:
            rid = recurrence_id.dt
            uid = f"{uid}#{rid.isoformat() if hasattr(rid, 'isoformat') else rid}"
        title = str(vevent.get("SUMMARY", "")) or "(no title)"
        return NormalizedEvent(
            title=title,
            start=start_utc,
            end=end_utc,
            calendar_name=calendar_name,
            all_day=all_day,
            external_uid=uid,
        )
    except Exception:
        logger.exception("Failed to normalize VEVENT; skipping")
        return None


def _calendar_display_name(calendar) -> str:
    name = getattr(calendar, "name", None)
    if name:
        return str(name)
    # Fall back to URL path tail; ``url`` is a URL object with ``path``.
    url = getattr(calendar, "url", None)
    if url is not None:
        path = getattr(url, "path", str(url))
        return str(path).rstrip("/").rsplit("/", 1)[-1] or "Calendar"
    return "Calendar"


def _expand_events(events_iter: Iterable, start: dt, end: dt) -> list:
    """Yield concrete VEVENTs for the window, expanding RRULE locally if
    the server returned masters with RRULE still present.

    Uses the Phase 0 spike's pinned accessor:
    ``event.icalendar_instance`` → ``recurring_ical_events.of(...)``.
    """
    out: list = []
    for raw_event in events_iter:
        try:
            ical_inst = raw_event.icalendar_instance
        except Exception:
            logger.exception("Failed to parse caldav.Event; skipping")
            continue
        try:
            occurrences = recurring_ical_events.of(ical_inst).between(start, end)
        except Exception:
            logger.exception("recurring_ical_events expansion failed; skipping")
            continue
        out.extend(occurrences)
    return out


def fetch_events_for_date(account, target_date: date) -> list[NormalizedEvent]:
    """Fetch and normalise CalDAV events for one date.

    The only function that decrypts the stored password. Wraps every
    provider error in the typed hierarchy so views translate to HTTP
    status without leaking caldav-lib types.
    """
    start, end = _day_window(target_date)
    password = account.get_password()  # only call site
    try:
        client = caldav.DAVClient(
            url=account.base_url,
            username=account.apple_id,
            password=password,
            timeout=settings.CALDAV_REQUEST_TIMEOUT,
        )
        principal = client.principal()
        normalized: list[NormalizedEvent] = []
        for calendar in principal.calendars():
            calendar_name = _calendar_display_name(calendar)
            try:
                raw_events = calendar.date_search(
                    start=start, end=end, expand=True
                )
            except AuthorizationError:
                raise
            except _TIMEOUT_EXC:
                raise
            except DAVError:
                # Real provider failure on a single calendar — propagate
                # so the outer handler wraps it as CalDAVProviderError →
                # 502. Swallowing here would yield a falsely-empty day
                # (single calendar) or silent partial data (multiple),
                # violating the acceptance criterion that provider
                # failures surface clearly.
                raise

            for vevent in _expand_events(raw_events, start, end):
                ev = _normalize_vevent(vevent, calendar_name)
                if ev is None:
                    continue
                # Defensive window guard — DAV servers occasionally
                # return events slightly outside the requested window.
                if ev.end <= _to_utc(start) or ev.start >= _to_utc(end):
                    continue
                normalized.append(ev)
        # Stable order so the UI doesn't shuffle between fetches.
        normalized.sort(key=lambda e: (e.start, e.title, e.external_uid))
        return normalized
    except AuthorizationError as e:
        raise CalDAVAuthError("CalDAV authentication failed") from e
    except _TIMEOUT_EXC as e:
        raise CalDAVTimeoutError("CalDAV request timed out") from e
    except DAVError as e:
        raise CalDAVProviderError("CalDAV provider error") from e
    except (CalDAVError, ImproperlyConfigured):
        # ImproperlyConfigured carries actionable ops detail (e.g. key
        # rotation invalidating stored ciphertext) — let it propagate
        # so the view can map it to a config-shaped 500 instead of a
        # provider-failure 502 that would point ops at iCloud.
        raise
    except Exception as e:
        raise CalDAVProviderError("CalDAV provider error") from e
    finally:
        # Defensive: drop local reference so the plaintext doesn't linger
        # in a frame any longer than necessary. CPython will still hold
        # it in the local until the frame unwinds; this is best-effort.
        password = None  # noqa: F841
