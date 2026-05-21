"""Versioned per-(user, date) cache for normalised CalDAV events.

Key shape: ``caldav_events:{user_id}:{account_version}:{date_iso}`` where
``account_version = account.updated_at.isoformat()`` (microsecond
precision via ``DateTimeField(auto_now=True)``). On credential rotation
or base-URL change, ``account.save()`` bumps ``updated_at`` and the next
read computes a fresh key — old entries become unreachable and expire
via TTL. There is no explicit "invalidate" call; that's the whole point
of the versioned design.

**auto_now footgun**: ``account.save(update_fields=[...])`` that omits
``"updated_at"`` bypasses ``auto_now`` and the key does NOT rotate —
serving stale events. Mutating call sites in ``views.py`` MUST either
call plain ``account.save()`` or include ``"updated_at"`` in
``update_fields``. Test #14 catches the runtime symptom; the docstring
on ``CalDAVAccount.set_password`` catches it at review time.
"""

from datetime import date

from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "caldav_events"


def events_cache_key(account, target_date: date) -> str:
    """Versioned cache key for ``(user, account_version, date)``.

    ``account.updated_at.isoformat()`` gives microsecond precision so
    two POSTs in the same second still produce distinct keys.
    """
    return (
        f"{_KEY_PREFIX}:{account.user_id}:"
        f"{account.updated_at.isoformat()}:{target_date.isoformat()}"
    )


def get_cached_events(account, target_date: date):
    return cache.get(events_cache_key(account, target_date))


def set_cached_events(account, target_date: date, events: list) -> None:
    cache.set(
        events_cache_key(account, target_date),
        events,
        settings.CALDAV_CACHE_TTL_SECONDS,
    )
