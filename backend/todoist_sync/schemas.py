"""Request/response schemas for the Todoist API endpoints.

Kept deliberately small — Django views do the validation inline rather
than reaching for a heavier schema lib. These helpers exist so the view
body stays focused on the happy path.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedTask:
    """The normalised task shape returned by ``service.fetch_tasks_for_date``.

    Fields match the response shape documented in the plan:
    ``id``, ``title``, ``priority``, ``ui_priority``, ``due_date``. The
    normaliser maps Todoist's raw ``content`` → ``title`` (the name
    ``content`` never reaches the wire payload). ``priority`` is the raw
    Todoist int (1–4 where 4 = P1/highest), kept for the deterministic
    sort; ``ui_priority`` is the precomputed inverted UI label
    (``P1..P4``, ``ui_priority = "P" + str(5 - priority)``). ``due_date``
    is an ISO date string (``YYYY-MM-DD``) or ``None`` when the source
    ``due`` is ``null`` (see ``service`` ``due`` normalisation).
    """

    id: str
    title: str
    priority: int
    ui_priority: str
    due_date: str | None


def normalized_task_to_dict(task: NormalizedTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "priority": task.priority,
        "ui_priority": task.ui_priority,
        "due_date": task.due_date,
    }


def validate_account_payload(data: dict) -> tuple[dict, dict]:
    """Validate the POST /api/todoist/account/ body.

    Returns ``(cleaned, errors)`` — ``errors`` is empty on success. Does
    not raise; the view translates ``errors`` to the standard envelope.
    """
    errors: dict = {}
    if not isinstance(data, dict):
        errors["detail"] = "Request body must be a JSON object."
        return {}, errors

    token = data.get("token")

    if not isinstance(token, str) or not token.strip():
        errors["token"] = "token is required."
    elif len(token) > 128:
        # Todoist personal API tokens are ~40 hex chars; 128 is ~3x the
        # longest realistic value and tight enough to reject pathological
        # payloads before they reach Fernet or the HTTP client.
        errors["token"] = "token is too long (max 128 characters)."

    if errors:
        errors.setdefault("detail", "Invalid request body.")
        return {}, errors

    cleaned = {
        "token": token.strip(),
    }
    return cleaned, {}
