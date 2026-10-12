"""Shared versioned cache-key pieces; providers keep their namespaces."""

from datetime import date

from django.utils import timezone


def versioned_key(
    namespace: str,
    account,
    target_date: date,
    time_zone: str,
    *,
    account_id: bool = False,
    task_scope: str | None = None,
) -> str:
    parts = [namespace, str(account.user_id)]
    if account_id:
        parts.append(str(account.id))
    parts.append(account.updated_at.isoformat())
    if task_scope is None:
        parts.extend((target_date.isoformat(), time_zone))
    else:
        parts.extend((time_zone, target_date.isoformat(), task_scope))
    return ":".join(parts)


def invalidate_account_version(account, model) -> None:
    """Rotate a cache version without saving stale credential fields."""
    now = timezone.now()
    model.objects.filter(pk=account.pk).update(updated_at=now)
    account.updated_at = now
