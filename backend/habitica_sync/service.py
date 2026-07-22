"""Habitica REST client wrapper for the habitica_sync app."""

import logging
from datetime import date

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as django_tz

from habitica_sync.schemas import NormalizedHabiticaTask

logger = logging.getLogger(__name__)


def is_project_today(target_date: date) -> bool:
    """Single source of truth for today-vs-exact cache/filter decisions."""
    return target_date == django_tz.localdate()


class HabiticaError(Exception):
    """Base for all Habitica service-layer errors."""


class HabiticaAuthError(HabiticaError):
    """Habitica rejected the credentials (401/403)."""


class HabiticaTimeoutError(HabiticaError):
    """Network timeout to Habitica."""


class HabiticaProviderError(HabiticaError):
    """Anything else from the REST layer."""


def _headers(api_user_id: str, token: str) -> dict[str, str]:
    """Habitica auth headers. Never log the token."""
    return {
        "x-api-user": api_user_id,
        "x-api-key": token,
        "x-client": f"{settings.HABITICA_CLIENT_ID}-DayForge",
        "Content-Type": "application/json",
    }


def _raise_for_status(response: requests.Response) -> None:
    if response.status_code in (401, 403):
        raise HabiticaAuthError("Habitica authentication failed")
    if not (200 <= response.status_code < 300):
        raise HabiticaProviderError("Habitica provider error")


def _unwrap_task_envelope(response: requests.Response) -> list:
    _raise_for_status(response)
    payload = response.json()
    if payload.get("success") is False:
        raise HabiticaProviderError("Habitica provider returned an error envelope")
    data = payload.get("data")
    if not isinstance(data, list):
        raise HabiticaProviderError("Habitica provider returned malformed task data")
    return data


def verify_credentials(api_user_id: str, token: str) -> None:
    """Prove the Habitica credentials with one authenticated task-list probe."""
    try:
        response = requests.get(
            f"{settings.HABITICA_BASE_URL}/tasks/user",
            params={"type": "todos"},
            headers=_headers(api_user_id, token),
            timeout=settings.HABITICA_REQUEST_TIMEOUT,
            # Habitica authenticates via CUSTOM headers, and requests only
            # strips ``Authorization`` on a cross-host redirect — ``x-api-key``
            # would be forwarded verbatim to the redirect target. Todoist gets
            # that protection for free from its Bearer header; we have to opt
            # out of redirects instead. The REST API never legitimately 3xxs.
            allow_redirects=False,
        )
        _unwrap_task_envelope(response)
    except HabiticaError:
        raise
    except requests.Timeout as e:
        raise HabiticaTimeoutError("Habitica request timed out") from e
    except requests.RequestException as e:
        raise HabiticaProviderError("Habitica provider error") from e
    except Exception as e:  # pragma: no cover - defensive
        raise HabiticaProviderError("Habitica provider error") from e


def _normalize_due_date(raw: str | None) -> str | None:
    if raw is None:
        return None
    if "T" in raw:
        return date.fromisoformat(raw[:10]).isoformat()
    return date.fromisoformat(raw).isoformat()


def _normalize_todo(task) -> NormalizedHabiticaTask:
    return NormalizedHabiticaTask(
        id=str(task["id"]),
        title=str(task["text"]),
        type="todo",
        due_date=_normalize_due_date(task.get("date")),
        completed=bool(task.get("completed")),
    )


def _normalize_daily(task) -> NormalizedHabiticaTask:
    return NormalizedHabiticaTask(
        id=str(task["id"]),
        title=str(task["text"]),
        type="daily",
        due_date=None,
        completed=bool(task.get("completed")),
    )


def _include_todo(
    task: NormalizedHabiticaTask,
    target_date: date,
    *,
    include_overdue_carryover: bool,
) -> bool:
    target = target_date.isoformat()
    if is_project_today(target_date) or include_overdue_carryover:
        if task.due_date is None:
            return True
        if task.due_date == target:
            return True
        return not task.completed and task.due_date < target
    return task.due_date == target


def _fetch_tasks(api_user_id: str, token: str, task_type: str) -> list:
    response = requests.get(
        f"{settings.HABITICA_BASE_URL}/tasks/user",
        params={"type": task_type},
        headers=_headers(api_user_id, token),
        timeout=settings.HABITICA_REQUEST_TIMEOUT,
    )
    return _unwrap_task_envelope(response)


def fetch_tasks_for_date(
    account,
    target_date: date,
    *,
    include_overdue_carryover: bool = False,
) -> list[NormalizedHabiticaTask]:
    """Fetch and normalise Habitica todos and due dailies for one date."""
    token = account.get_token()
    try:
        normalized: list[NormalizedHabiticaTask] = []
        for raw in _fetch_tasks(account.api_user_id, token, "todos"):
            try:
                task = _normalize_todo(raw)
                if not task.completed and _include_todo(
                    task,
                    target_date,
                    include_overdue_carryover=include_overdue_carryover,
                ):
                    normalized.append(task)
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(
                    "Failed to normalize Habitica todo (%s: %s); skipping",
                    type(e).__name__,
                    e,
                )

        if is_project_today(target_date) or include_overdue_carryover:
            for raw in _fetch_tasks(account.api_user_id, token, "dailys"):
                try:
                    task = _normalize_daily(raw)
                    if raw.get("isDue") is True and not task.completed:
                        normalized.append(task)
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(
                        "Failed to normalize Habitica daily (%s: %s); skipping",
                        type(e).__name__,
                        e,
                    )

        normalized.sort(
            key=lambda t: (
                -int(t.type == "daily"),
                t.due_date or "9999-12-31",
                t.title.casefold(),
                t.id,
            )
        )
        return normalized
    except HabiticaError:
        raise
    except requests.Timeout as e:
        raise HabiticaTimeoutError("Habitica request timed out") from e
    except requests.RequestException as e:
        raise HabiticaProviderError("Habitica provider error") from e
    except ImproperlyConfigured:
        raise
    except Exception as e:
        raise HabiticaProviderError("Habitica provider error") from e
    finally:
        del token


def complete_task(account, task_id: str) -> None:
    """Score up one Habitica todo or daily."""
    token = account.get_token()
    try:
        response = requests.post(
            f"{settings.HABITICA_BASE_URL}/tasks/{task_id}/score/up",
            headers=_headers(account.api_user_id, token),
            json={},
            timeout=settings.HABITICA_REQUEST_TIMEOUT,
        )
        _raise_for_status(response)
    except HabiticaError:
        raise
    except requests.Timeout as e:
        raise HabiticaTimeoutError("Habitica request timed out") from e
    except requests.RequestException as e:
        raise HabiticaProviderError("Habitica provider error") from e
    except ImproperlyConfigured:
        raise
    except Exception as e:
        raise HabiticaProviderError("Habitica provider error") from e
    finally:
        del token
