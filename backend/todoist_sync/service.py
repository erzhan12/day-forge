"""Todoist REST client wrapper for the todoist_sync app.

**Service-boundary owns the secret.** ``fetch_tasks_for_date`` is the
ONLY function that calls ``account.get_token()``. Views pass the
``TodoistAccount`` instance through; they never touch the plaintext. This
keeps the decryption surface to a single file and makes the
"token never logged" test tractable.

The Todoist API v1 host is ``https://api.todoist.com/api/v1`` (the real
API host, parameterised as ``settings.TODOIST_BASE_URL`` — never the
``developer.todoist.com`` docs host, which 404s/returns HTML).
"""

import logging
from datetime import date

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone as django_tz

from todoist_sync.schemas import NormalizedTask

logger = logging.getLogger(__name__)

# The dedicated filter endpoint is cursor-paginated; ``limit`` maxes at 200.
_FILTER_PAGE_LIMIT = 200

# Hard ceiling on pagination loops. A well-behaved API terminates by
# returning a null ``next_cursor``; this guards against a misbehaving or
# malicious endpoint (``TODOIST_BASE_URL`` is operator-configurable, so a
# proxy could return an endless cursor) pinning a worker forever — the same
# worker-protection rationale as ``TODOIST_REQUEST_TIMEOUT``. 200 pages ×
# 200 tasks = 40k, far above any real Todoist account, so legitimate fetches
# never hit it. We RAISE (never silently truncate — the plan mandates
# fetching all matching tasks), surfacing as a 502 rather than a hang.
_MAX_FILTER_PAGES = 200


# ----- Typed exception hierarchy -----------------------------------------

class TodoistError(Exception):
    """Base for all Todoist service-layer errors."""


class TodoistAuthError(TodoistError):
    """Todoist rejected the token (401/403)."""


class TodoistTimeoutError(TodoistError):
    """Network timeout to Todoist."""


class TodoistProviderError(TodoistError):
    """Anything else from the REST layer — wrap to keep views simple."""


# ----- HTTP helpers ------------------------------------------------------

def _headers(token: str) -> dict[str, str]:
    """Authorization header for a Bearer token. Never logged."""
    return {"Authorization": f"Bearer {token}"}


def _raise_for_status(response: requests.Response) -> None:
    """Map a non-2xx Todoist response onto the typed hierarchy.

    401/403 → auth; everything else → provider. Never logs the token.
    """
    if response.status_code in (401, 403):
        raise TodoistAuthError("Todoist authentication failed")
    if not (200 <= response.status_code < 300):
        raise TodoistProviderError("Todoist provider error")


# ----- verify_credentials ------------------------------------------------

def verify_credentials(token: str) -> None:
    """Prove the Bearer token works with a single cheap authenticated call.

    Probes ``GET /projects?limit=1`` — NOT ``/tasks/filter`` (whose
    ``query`` param is required, so a missing/empty query is a 400, not an
    auth signal). A single Bearer-token call suffices: the token is
    all-or-nothing, so no second probe is needed (unlike CalDAV, which can
    partially succeed on incomplete creds).

    Raises a typed ``TodoistError`` subclass on failure; returns ``None``
    on success. Never logs the token.
    """
    try:
        response = requests.get(
            f"{settings.TODOIST_BASE_URL}/projects",
            params={"limit": 1},
            headers=_headers(token),
            timeout=settings.TODOIST_REQUEST_TIMEOUT,
        )
        _raise_for_status(response)
    except TodoistError:
        raise
    except requests.Timeout as e:
        raise TodoistTimeoutError("Todoist request timed out") from e
    except requests.RequestException as e:
        raise TodoistProviderError("Todoist provider error") from e
    except Exception as e:  # pragma: no cover - defensive
        raise TodoistProviderError("Todoist provider error") from e


# ----- fetch_tasks_for_date ----------------------------------------------

# Todoist ``priority`` is an int 4..1 where 4 is the highest (P1). The UI
# label is inverted: ``ui_priority = "P" + str(5 - priority)``.
def _ui_priority(priority: int) -> str:
    return f"P{5 - priority}"


def _normalize_due_date(due) -> str | None:
    """Map Todoist's polymorphic ``due`` object onto an ISO date string.

    ``due`` is either ``null`` or ``{date, timezone, is_recurring, string,
    lang}`` (there is no ``datetime`` field). The ``date`` field is
    polymorphic: full-day tasks return ``"2025-02-12"`` (``YYYY-MM-DD``);
    timed tasks return a full datetime in the *same* key, e.g.
    ``"2018-11-15T12:00:00.000000"`` (possibly with a ``Z``/offset suffix).

    The time component is intentionally dropped (date-only display). The
    ``raw[:10]`` slice is suffix-agnostic, so it yields the correct
    ``YYYY-MM-DD`` for both full-day and timed values. Calling
    ``date.fromisoformat`` on the raw value would raise on every timed task.
    """
    if due is None:
        return None
    raw = due["date"]
    if "T" in raw:
        return date.fromisoformat(raw[:10]).isoformat()
    return date.fromisoformat(raw).isoformat()


def _normalize_task(task) -> NormalizedTask:
    """Build a NormalizedTask from one raw Todoist task.

    Maps the raw ``content`` field onto ``title`` (``content`` never
    reaches the wire payload). Emits both the raw ``priority`` int (for the
    deterministic sort) and the precomputed ``ui_priority`` string so the
    derivation lives in one place.
    """
    priority = int(task["priority"])
    return NormalizedTask(
        id=str(task["id"]),
        title=str(task["content"]),
        priority=priority,
        ui_priority=_ui_priority(priority),
        due_date=_normalize_due_date(task.get("due")),
    )


def _filter_query(target_date: date, *, include_overdue_carryover: bool = False) -> str:
    """Map the selected date to a Todoist filter query.

    When the schedule date is "today" (project ``TIME_ZONE``) **or** the
    client requests overdue carryover (browser-local today can differ from
    ``localdate()`` when ``TIME_ZONE`` is UTC and the user is ahead), use
    ``"<YYYY-MM-DD> | overdue"`` — tasks due on that date plus all past-due
    tasks. Pinning the literal date (not Todoist's ``today`` token) keeps
    the window aligned with the selected schedule day.

  Otherwise → the bare literal-date token ``"<YYYY-MM-DD>"``, which Todoist
    interprets as "due on that date" (``due:`` semantics). Do NOT use the
    ``date:`` keyword, which scopes by absolute date and ignores recurrence.
    """
    is_project_today = target_date == django_tz.localdate()
    if is_project_today or include_overdue_carryover:
        return f"{target_date.isoformat()} | overdue"
    return target_date.isoformat()


def _fetch_filtered_tasks(query: str, token: str) -> list:
    """Fetch all matching tasks from the cursor-paginated filter endpoint.

    Issues ``GET /tasks/filter?query=<q>&limit=200`` and loops while the
    response ``next_cursor`` is non-null, concatenating ``results`` — a
    single un-paginated call would silently drop tasks for a large
    overdue backlog.
    """
    url = f"{settings.TODOIST_BASE_URL}/tasks/filter"
    raw_tasks: list = []
    cursor = None
    for _page in range(_MAX_FILTER_PAGES):
        params = {"query": query, "limit": _FILTER_PAGE_LIMIT}
        if cursor is not None:
            params["cursor"] = cursor
        response = requests.get(
            url,
            params=params,
            headers=_headers(token),
            timeout=settings.TODOIST_REQUEST_TIMEOUT,
        )
        _raise_for_status(response)
        payload = response.json()
        raw_tasks.extend(payload.get("results", []))
        cursor = payload.get("next_cursor")
        if not cursor:
            return raw_tasks
    # Exhausted the page ceiling without a terminating null cursor — the
    # endpoint is misbehaving. Raise rather than silently truncate or loop
    # forever (worker protection; never drops tasks on a well-behaved API).
    raise TodoistProviderError(
        f"Todoist filter pagination exceeded {_MAX_FILTER_PAGES} pages"
    )


def fetch_tasks_for_date(
    account,
    target_date: date,
    *,
    include_overdue_carryover: bool = False,
) -> list[NormalizedTask]:
    """Fetch and normalise Todoist tasks for one date.

    The only function that decrypts the stored token. Wraps every provider
    error in the typed hierarchy so views translate to HTTP status without
    leaking requests-lib types. Lets ``ImproperlyConfigured`` (key rotation)
    propagate so the view maps it to a config-shaped 500.
    """
    query = _filter_query(
        target_date, include_overdue_carryover=include_overdue_carryover
    )
    token = account.get_token()  # only call site
    try:
        raw_tasks = _fetch_filtered_tasks(query, token)
        normalized: list[NormalizedTask] = []
        for raw in raw_tasks:
            try:
                normalized.append(_normalize_task(raw))
            except (KeyError, ValueError, TypeError) as e:
                # A single malformed task must not fail the whole fetch.
                # Bug-class errors (NameError, ImportError) propagate so
                # real defects surface.
                logger.warning(
                    "Failed to normalize task (%s: %s); skipping",
                    type(e).__name__,
                    e,
                )
                continue
        # Stable order so the UI doesn't shuffle between fetches. Null-safe
        # key: ``due_date`` is nullable (``due == null`` → ``None``) and a
        # bare tuple would raise comparing ``None`` against a ``str`` date.
        normalized.sort(
            key=lambda t: (-t.priority, t.due_date or "", t.title.casefold(), t.id)
        )
        return normalized
    except TodoistError:
        raise
    except requests.Timeout as e:
        raise TodoistTimeoutError("Todoist request timed out") from e
    except requests.RequestException as e:
        raise TodoistProviderError("Todoist provider error") from e
    except ImproperlyConfigured:
        # ImproperlyConfigured carries actionable ops detail (e.g. key
        # rotation invalidating stored ciphertext) — let it propagate so
        # the view can map it to a config-shaped 500 instead of a
        # provider-failure 502 that would point ops at Todoist.
        raise
    except Exception as e:
        raise TodoistProviderError("Todoist provider error") from e
    finally:
        # Defensive: drop the local binding so the plaintext doesn't linger
        # in the frame's locals dict any longer than necessary. ``del``
        # makes intent explicit; the binding is unreachable afterwards.
        del token
