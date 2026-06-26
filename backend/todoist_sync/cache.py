"""Versioned per-(user, date) cache for normalised Todoist tasks.

Key shape: ``todoist_tasks:{user_id}:{account_version}:{date_iso}`` where
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

from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "todoist_tasks"


def tasks_filter_scope(
    target_date: date, *, include_overdue_carryover: bool = False
) -> str:
    """Cache-scope tag for the filter mode used on this read.

    ``with_overdue`` and ``exact`` must not share a cache entry — the
    overdue carryover query returns a strict superset of the bare-date
    query. Uses ``service.is_project_today`` (the single source of truth)
    so this scope tag can never drift from the filter the query actually
    used — drift would serve stale/wrong tasks.
    """
    from todoist_sync.service import is_project_today

    if include_overdue_carryover or is_project_today(target_date):
        return "with_overdue"
    return "exact"


def tasks_cache_key(
    account, target_date: date, *, filter_scope: str = "exact"
) -> str:
    """Versioned cache key for ``(user, account_version, date, filter_scope)``.

    ``account.updated_at.isoformat()`` gives microsecond precision so
    two POSTs in the same second still produce distinct keys.
    """
    return (
        f"{_KEY_PREFIX}:{account.user_id}:"
        f"{account.updated_at.isoformat()}:{target_date.isoformat()}:{filter_scope}"
    )


def get_cached_tasks(
    account, target_date: date, *, filter_scope: str = "exact"
):
    return cache.get(tasks_cache_key(account, target_date, filter_scope=filter_scope))


def set_cached_tasks(
    account, target_date: date, tasks: list, *, filter_scope: str = "exact"
) -> None:
    cache.set(
        tasks_cache_key(account, target_date, filter_scope=filter_scope),
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
    from django.utils import timezone

    from todoist_sync.models import TodoistAccount

    now = timezone.now()
    TodoistAccount.objects.filter(pk=account.pk).update(updated_at=now)
    account.updated_at = now
