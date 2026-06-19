"""Versioned per-(user, date) cache for normalised Todoist tasks.

Key shape: ``todoist_tasks:{user_id}:{account_version}:{date_iso}`` where
``account_version = account.updated_at.isoformat()`` (microsecond
precision via ``DateTimeField(auto_now=True)``). On token rotation,
``account.save()`` bumps ``updated_at`` and the next read computes a
fresh key — old entries become unreachable and expire via TTL. There is
no explicit "invalidate" call; that's the whole point of the versioned
design.

**auto_now footgun**: ``account.save(update_fields=[...])`` that omits
``"updated_at"`` bypasses ``auto_now`` and the key does NOT rotate —
serving stale tasks. Mutating call sites in ``views.py`` MUST either
call plain ``account.save()`` or include ``"updated_at"`` in
``update_fields``. A view test catches the runtime symptom; the
docstring on ``TodoistAccount.set_token`` catches it at review time.
"""

from datetime import date

from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "todoist_tasks"


def tasks_cache_key(account, target_date: date) -> str:
    """Versioned cache key for ``(user, account_version, date)``.

    ``account.updated_at.isoformat()`` gives microsecond precision so
    two POSTs in the same second still produce distinct keys.
    """
    return (
        f"{_KEY_PREFIX}:{account.user_id}:"
        f"{account.updated_at.isoformat()}:{target_date.isoformat()}"
    )


def get_cached_tasks(account, target_date: date):
    return cache.get(tasks_cache_key(account, target_date))


def set_cached_tasks(account, target_date: date, tasks: list) -> None:
    cache.set(
        tasks_cache_key(account, target_date),
        tasks,
        settings.TODOIST_CACHE_TTL_SECONDS,
    )
