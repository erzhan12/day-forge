"""Validation helpers for AI command responses.

The LLM is called with ``response_format={"type": "json_object"}`` (not
``json_schema`` strict mode — see ``ai/service.py`` for the rationale:
``LLM_BASE_URL`` provider-compatibility). The JSON shape is described in
the system prompt (``ai/prompts.py``), and because the provider is not
held to a strict schema at the network layer, every response is
revalidated here before it can touch the DB. These validators are the
primary enforcement, not a belt-and-suspenders check.
"""
import datetime
import re

from schedules.http import is_plain_int

MAX_ACTIONS_PER_COMMAND = 20

ALLOWED_ACTION_TYPES = {"add", "move", "remove", "resize"}

# Fields expected per action type. ``task_id`` is always an int; time fields
# use HH:MM.
_REQUIRED_FIELDS = {
    "add": {"title", "start_time", "end_time", "category"},
    "move": {"task_id"},
    "remove": {"task_id"},
    "resize": {"task_id"},
}

_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

MAX_TITLE_LEN = 255
MAX_EXPLANATION_LEN = 500


def _is_hhmm(value) -> bool:
    return isinstance(value, str) and bool(_TIME_PATTERN.match(value))


def validate_action_shape(action, allowed_categories) -> list[str]:
    """Return a list of per-action error strings. Empty list means OK.

    Checks types and enum membership only — business rules like "block is on
    the right schedule" or "no overlap" are enforced by the view.
    """
    errors: list[str] = []
    if not isinstance(action, dict):
        return ["action must be an object"]

    action_type = action.get("type")
    if action_type not in ALLOWED_ACTION_TYPES:
        return [
            f"type must be one of {sorted(ALLOWED_ACTION_TYPES)}, got {action_type!r}"
        ]

    for field in _REQUIRED_FIELDS[action_type]:
        if field not in action:
            errors.append(f"{action_type} action requires '{field}'")

    # ``move`` and ``resize`` only require ``task_id`` structurally, but a
    # payload with no time fields would apply as a silent no-op — the AI
    # would "succeed" without actually doing what the user asked. Reject
    # at the schema layer so the view never sees it.
    if action_type in {"move", "resize"}:
        if "start_time" not in action and "end_time" not in action:
            errors.append(
                f"{action_type} action requires at least one of "
                "'start_time' or 'end_time'"
            )

    if "task_id" in action and not is_plain_int(action["task_id"]):
        errors.append("task_id must be an integer")

    if "title" in action:
        title = action["title"]
        if not isinstance(title, str):
            errors.append("title must be a string")
        elif not title.strip():
            errors.append("title cannot be empty")
        elif len(title) > MAX_TITLE_LEN:
            errors.append(f"title must be <= {MAX_TITLE_LEN} chars")
        elif any(ord(c) < 32 and c not in "\t\n\r" for c in title):
            # Reject NUL and other unprintable control chars that could
            # corrupt downstream consumers (CSV exports, log scrapers).
            # Tab/newline/CR are allowed since users may legitimately
            # paste multi-line titles.
            errors.append("title contains invalid control characters")

    for time_field in ("start_time", "end_time"):
        if time_field in action and not _is_hhmm(action[time_field]):
            errors.append(f"{time_field} must be HH:MM")

    if "category" in action and action["category"] not in allowed_categories:
        errors.append(
            f"category must be one of {sorted(allowed_categories)}"
        )

    # For add, both times are required and must form a valid window.
    if action_type == "add" and _is_hhmm(action.get("start_time", "")) and _is_hhmm(
        action.get("end_time", "")
    ):
        start = datetime.datetime.strptime(action["start_time"], "%H:%M").time()
        end = datetime.datetime.strptime(action["end_time"], "%H:%M").time()
        if start >= end:
            errors.append("start_time must be before end_time")

    return errors


def validate_response_envelope(parsed) -> list[str]:
    """Sanity-check the top-level shape before inspecting individual actions."""
    if not isinstance(parsed, dict):
        return ["response must be a JSON object"]

    errors: list[str] = []
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        errors.append("'actions' must be an array")
    elif len(actions) > MAX_ACTIONS_PER_COMMAND:
        errors.append(
            f"too many actions ({len(actions)} > {MAX_ACTIONS_PER_COMMAND})"
        )

    explanation = parsed.get("explanation", "")
    if not isinstance(explanation, str):
        errors.append("'explanation' must be a string")
    elif len(explanation) > MAX_EXPLANATION_LEN:
        errors.append(
            f"'explanation' must be <= {MAX_EXPLANATION_LEN} chars"
        )

    return errors
