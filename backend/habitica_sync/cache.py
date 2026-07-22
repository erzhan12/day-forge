"""Versioned per-(user, date, scope) cache for normalised Habitica tasks."""

from datetime import date

from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "habitica_tasks"


def tasks_filter_scope(
    target_date: date, *, include_overdue_carryover: bool = False
) -> str:
    """Cache-scope tag for the filter mode used on this read."""
    from habitica_sync.service import is_project_today

    if include_overdue_carryover or is_project_today(target_date):
        return "with_overdue"
    return "exact"


def tasks_cache_key(
    account, target_date: date, *, filter_scope: str = "exact"
) -> str:
    return (
        f"{_KEY_PREFIX}:{account.user_id}:"
        f"{account.updated_at.isoformat()}:{target_date.isoformat()}:{filter_scope}"
    )


def get_cached_tasks(account, target_date: date, *, filter_scope: str = "exact"):
    return cache.get(tasks_cache_key(account, target_date, filter_scope=filter_scope))


def set_cached_tasks(
    account, target_date: date, tasks: list, *, filter_scope: str = "exact"
) -> None:
    cache.set(
        tasks_cache_key(account, target_date, filter_scope=filter_scope),
        tasks,
        settings.HABITICA_CACHE_TTL_SECONDS,
    )


def invalidate_tasks(account) -> None:
    """Invalidate every cached task list for ``account`` with a version bump."""
    from django.utils import timezone

    from habitica_sync.models import HabiticaAccount

    now = timezone.now()
    HabiticaAccount.objects.filter(pk=account.pk).update(updated_at=now)
    account.updated_at = now
