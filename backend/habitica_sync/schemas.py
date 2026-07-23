"""Request/response schemas for the Habitica API endpoints."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedHabiticaTask:
    id: str
    title: str
    type: str
    due_date: str | None
    completed: bool
    position: int = 0


def normalized_task_to_dict(task: NormalizedHabiticaTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "type": task.type,
        "due_date": task.due_date,
        "completed": task.completed,
    }


def validate_account_payload(data: dict) -> tuple[dict, dict]:
    """Validate the POST /api/habitica/account/ body."""
    errors: dict = {}
    if not isinstance(data, dict):
        errors["detail"] = "Request body must be a JSON object."
        return {}, errors

    api_user_id = data.get("api_user_id")
    api_token = data.get("api_token")

    if not isinstance(api_user_id, str) or not api_user_id.strip():
        errors["api_user_id"] = "api_user_id is required."
    elif len(api_user_id) > 128:
        errors["api_user_id"] = "api_user_id is too long (max 128 characters)."

    if not isinstance(api_token, str) or not api_token.strip():
        errors["api_token"] = "api_token is required."
    elif len(api_token) > 128:
        errors["api_token"] = "api_token is too long (max 128 characters)."

    if errors:
        errors.setdefault("detail", "Invalid request body.")
        return {}, errors

    return {
        "api_user_id": api_user_id.strip(),
        "api_token": api_token.strip(),
    }, {}
