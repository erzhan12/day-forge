"""Versioned per-(user, account, date) cache for normalised Google events.

Key shape:
``gcal_events:{user_id}:{account_id}:{account_version}:{date_iso}`` where
``account_version = account.updated_at.isoformat()`` (microsecond precision
via ``DateTimeField(auto_now=True)``). The key includes ``account.id``
because a user has **many** Google accounts (the CalDAV key only needed
``user_id``). On token refresh / reconnect, ``account.save()`` bumps
``updated_at`` and the next read computes a fresh key — old entries become
unreachable and expire via TTL. No explicit invalidation call.

**Async helpers (``aget`` / ``aset``):** the only caller is the **async**
events view, so these MUST use the async cache API — synchronous
``cache.get`` / ``cache.set`` under ``RedisCache`` are blocking network I/O
that would stall the ASGI event loop. (The ``aincr`` non-atomic-RMW footgun
is specific to the rate-limiter's counter; these are plain idempotent
versioned-key get/set, so ``aget``/``aset`` are both correct and
non-blocking.)

**auto_now footgun**: ``account.save(update_fields=[...])`` that omits
``"updated_at"`` bypasses ``auto_now`` and the key does NOT rotate —
serving stale events. Mutating call sites MUST call plain ``account.save()``
or include ``"updated_at"`` in ``update_fields``.
"""

from datetime import date

from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "gcal_events"


def events_cache_key(account, target_date: date) -> str:
    """Versioned cache key for ``(user, account, account_version, date)``."""
    return (
        f"{_KEY_PREFIX}:{account.user_id}:{account.id}:"
        f"{account.updated_at.isoformat()}:{target_date.isoformat()}"
    )


async def get_cached_events(account, target_date: date):
    return await cache.aget(events_cache_key(account, target_date))


async def set_cached_events(account, target_date: date, events: list) -> None:
    await cache.aset(
        events_cache_key(account, target_date),
        events,
        settings.GOOGLE_CACHE_TTL_SECONDS,
    )
