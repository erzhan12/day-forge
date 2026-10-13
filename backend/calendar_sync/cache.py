"""Versioned per-(user, date, timezone) cache for CalDAV events.

Key shape: ``caldav_events:v2:{user_id}:{account_version}:{date_iso}:{time_zone}`` where
``account_version = account.updated_at.isoformat()`` (microsecond
precision via ``DateTimeField(auto_now=True)``). On credential rotation
or base-URL change, ``account.save()`` bumps ``updated_at``. A timezone
change also produces a different key. The ``v2`` namespace leaves older
entries unreachable until they expire.

**auto_now footgun**: ``account.save(update_fields=[...])`` that omits
``"updated_at"`` bypasses ``auto_now`` and the key does NOT rotate —
serving stale events. Mutating call sites in ``views.py`` MUST either
call plain ``account.save()`` or include ``"updated_at"`` in
``update_fields``. Test #14 catches the runtime symptom; the docstring
on ``CalDAVAccount.set_password`` catches it at review time.
"""

from datetime import date

from common.integration_cache import versioned_key
from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "caldav_events:v2"


def events_cache_key(account, target_date: date, time_zone: str = "UTC") -> str:
    """Versioned cache key for ``(user, account_version, date, timezone)``.

    ``account.updated_at.isoformat()`` gives microsecond precision so
    two POSTs in the same second still produce distinct keys.
    """
    return versioned_key(_KEY_PREFIX, account, target_date, time_zone)


def get_cached_events(account, target_date: date, time_zone: str = "UTC"):
    return cache.get(events_cache_key(account, target_date, time_zone))


def set_cached_events(account, target_date: date, events: list, time_zone: str = "UTC") -> None:
    cache.set(
        events_cache_key(account, target_date, time_zone),
        events,
        settings.CALDAV_CACHE_TTL_SECONDS,
    )
