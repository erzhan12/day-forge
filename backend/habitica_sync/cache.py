"""Versioned per-(user, date, scope) cache for normalised Habitica tasks."""

from datetime import date

from common.integration_cache import invalidate_account_version, versioned_key
from django.conf import settings
from django.core.cache import cache

_KEY_PREFIX = "habitica_tasks"


def tasks_filter_scope(target_date: date, *, local_today: date) -> str:
    """Cache-scope tag for the filter mode used on this read."""
    from habitica_sync.service import is_user_today

    if is_user_today(target_date, local_today=local_today):
        return "with_overdue"
    return "exact"


def tasks_cache_key(
    account, target_date: date, *, time_zone: str, filter_scope: str = "exact"
) -> str:
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
        settings.HABITICA_CACHE_TTL_SECONDS,
    )


def invalidate_tasks(account) -> None:
    """Invalidate every cached task list for ``account`` with a version bump."""
    from habitica_sync.models import HabiticaAccount

    invalidate_account_version(account, HabiticaAccount)
