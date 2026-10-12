"""Versioned per-(user, date) cache for normalised Todoist tasks.

Key shape: ``todoist_tasks:{user_id}:{account_version}:{time_zone}:{date_iso}:{scope}`` where
``account_version = account.updated_at.isoformat()`` (microsecond
precision via ``DateTimeField(auto_now=True)``). On token rotation,
``account.save()`` bumps ``updated_at`` and the next read computes a
fresh key — old entries become unreachable and expire via TTL. The
versioned design avoids key-enumeration: ``invalidate_tasks(account)``
exists (called after a successful task complete) but is NOT a key
deletion — it bumps ``account.updated_at`` (plain ``account.save()``) so
the version rotates and every existing ``todoist_tasks:*`` key for that
user becomes unreachable at once, with no key enumeration.

**auto_now footgun**: ``account.save(update_fields=[...])`` that omits
``"updated_at"`` bypasses ``auto_now`` and the key does NOT rotate —
serving stale tasks. Mutating call sites in ``views.py`` MUST either
call plain ``account.save()`` or include ``"updated_at"`` in
``update_fields``. A view test catches the runtime symptom; the
docstring on ``TodoistAccount.set_token`` catches it at review time.
"""

from datetime import date

from common.integration_cache import invalidate_account_version, versioned_key
from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "todoist_tasks"


def tasks_filter_scope(target_date: date, *, local_today: date) -> str:
    """Cache-scope tag for the filter mode used on this read.

    ``with_overdue`` and ``exact`` cannot share a cache entry. The same
    request-local date snapshot drives this tag and the provider filter.
    """
    from todoist_sync.service import is_user_today

    if is_user_today(target_date, local_today=local_today):
        return "with_overdue"
    return "exact"


def tasks_cache_key(
    account, target_date: date, *, time_zone: str, filter_scope: str = "exact"
) -> str:
    """Versioned cache key for user, account, timezone, date and scope.

    ``account.updated_at.isoformat()`` gives microsecond precision so
    two POSTs in the same second still produce distinct keys.
    """
    return versioned_key(_KEY_PREFIX, account, target_date, time_zone, task_scope=filter_scope)


def get_cached_tasks(account, target_date: date, *, time_zone: str, filter_scope: str = "exact"):
    return cache.get(
        tasks_cache_key(account, target_date, time_zone=time_zone, filter_scope=filter_scope)
    )


def set_cached_tasks(
    account, target_date: date, tasks: list, *, time_zone: str, filter_scope: str = "exact"
) -> None:
    cache.set(
        tasks_cache_key(account, target_date, time_zone=time_zone, filter_scope=filter_scope),
        tasks,
        settings.TODOIST_CACHE_TTL_SECONDS,
    )


def invalidate_tasks(account) -> None:
    """Invalidate every cached task list for ``account`` at once.

    Bumps ``account.updated_at`` so the ``account_version`` segment of every
    ``todoist_tasks:*`` key rotates — all existing entries (across all
    dates/scopes) become unreachable without any key enumeration
    (versioned-key design; see module docstring). Called after a successful
    task complete so the just-closed task is not served from a stale cache
    for up to the TTL.

    Uses ``QuerySet.update(updated_at=…)`` rather than ``account.save()`` so
    a stale in-memory instance (e.g. loaded at the start of an in-flight
    complete while a concurrent account POST rotated the token, or DELETE
    removed the row) cannot clobber ``token_encrypted`` or resurrect a
    deleted account.

    **auto_now footgun (critical):** ``QuerySet.update()`` bypasses
    ``auto_now`` entirely, so ``updated_at`` MUST be set explicitly here.
    Other mutating call sites (``views.py``, ``models.py:set_token``) still
    rely on a plain ``account.save()`` (or an ``update_fields`` that
    includes ``"updated_at"``) to fire ``auto_now`` — see module docstring.
    """
    # Imports inside the function avoid a circular dependency
    # (cache.py ← models.py → cache.py) at module load.
    from todoist_sync.models import TodoistAccount

    invalidate_account_version(account, TodoistAccount)
