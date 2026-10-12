"""Versioned per-(user, account, date, timezone) Google event cache.

Key shape:
``gcal_events:v2:{user_id}:{account_id}:{account_version}:{date_iso}:{time_zone}`` where
``account_version = account.updated_at.isoformat()`` (microsecond precision
via ``DateTimeField(auto_now=True)``). The key includes ``account.id``
because a user has **many** Google accounts (the CalDAV key only needed
``user_id``). Token refresh, reconnect, and timezone changes produce new
keys. The ``v2`` namespace leaves older entries unreachable until TTL expiry.

The async events view calls these helpers. ``sync_to_async`` sends cache I/O
to a worker thread, including network I/O from a Redis cache backend.

**auto_now footgun**: ``account.save(update_fields=[...])`` that omits
``"updated_at"`` bypasses ``auto_now`` and the key does NOT rotate —
serving stale events. Mutating call sites MUST call plain ``account.save()``
or include ``"updated_at"`` in ``update_fields``.
"""

from datetime import date

from asgiref.sync import sync_to_async
from common.integration_cache import versioned_key
from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "gcal_events:v2"


def events_cache_key(account, target_date: date, time_zone: str = "UTC") -> str:
    """Versioned key for user, account, account version, date and timezone."""
    return versioned_key(_KEY_PREFIX, account, target_date, time_zone, account_id=True)


async def get_cached_events(account, target_date: date, time_zone: str = "UTC"):
    return await sync_to_async(cache.get)(events_cache_key(account, target_date, time_zone))


async def set_cached_events(
    account, target_date: date, events: list, time_zone: str = "UTC"
) -> None:
    await sync_to_async(cache.set)(
        events_cache_key(account, target_date, time_zone),
        events,
        settings.GOOGLE_CACHE_TTL_SECONDS,
    )
