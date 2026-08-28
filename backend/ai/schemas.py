"""Validation helpers for AI chat and draft responses.

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

from django.conf import settings
from schedules.http import is_plain_int

from ai.free_slot import GRID_MINUTES

MAX_ACTIONS_PER_COMMAND = 20

ALLOWED_ACTION_TYPES = {"add", "move", "remove", "resize", "update"}

# Feature 0067: allowed keys on an ``add`` action. A key outside this set (e.g.
# a misspelled ``start``/``end``) is rejected rather than silently ignored,
# which would otherwise misclassify a mistyped explicit add as an untimed add.
_ADD_ALLOWED_KEYS = {"type", "title", "category", "start_time", "end_time", "duration_minutes"}

# Fields expected per action type. ``task_id`` is always an int; time fields
# use HH:MM.
_REQUIRED_FIELDS = {
    "add": {"title", "start_time", "end_time", "category"},
    "move": {"task_id"},
    "remove": {"task_id"},
    "resize": {"task_id"},
    "update": {"task_id"},
}

_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

MAX_TITLE_LEN = 255
# Note: explanation length is capped via ``settings.LLM_MAX_EXPLANATION_CHARS``
# (default 300). Reading the setting at validation time keeps chat and
# one-shot endpoints in sync without duplicating the constant here.


def _is_hhmm(value) -> bool:
    return isinstance(value, str) and bool(_TIME_PATTERN.match(value))


def validate_action_shape(
    action, allowed_categories, *, allow_untimed_add: bool = False
) -> list[str]:
    """Return a list of per-action error strings. Empty list means OK.

    Checks types and enum membership only — business rules like "block is on
    the right schedule" or "no overlap" are enforced by the view.

    ``allow_untimed_add`` (feature 0067) is passed ``True`` only from the chat
    per-action loop (``service.run_chat``). When true, an ``add`` may omit BOTH
    ``start_time`` and ``end_time`` (deterministic backend placement) and may
    carry an optional ``duration_minutes``. The draft path leaves it ``False``,
    so a draft ``add`` still requires both times.
    """
    errors: list[str] = []
    if not isinstance(action, dict):
        return ["action must be an object"]

    action_type = action.get("type")
    if action_type not in ALLOWED_ACTION_TYPES:
        return [f"type must be one of {sorted(ALLOWED_ACTION_TYPES)}, got {action_type!r}"]

    # Feature 0067: an untimed chat add classifies by time-key presence. Reject
    # unknown keys first so a misspelled ``start``/``end`` cannot masquerade as
    # a valid untimed add and get auto-placed. ``duration_minutes`` is valid on
    # a chat untimed add OR as the sole duration operand of a resize (feature
    # 0068) — rejected on explicit adds and everywhere else below.
    if action_type == "add":
        unknown = set(action) - _ADD_ALLOWED_KEYS
        if unknown:
            errors.append(f"add action has unknown key(s): {sorted(unknown)}")
        has_start = "start_time" in action
        has_end = "end_time" in action
        if allow_untimed_add:
            # Require only title + category; both-or-neither on times.
            for field in ("title", "category"):
                if field not in action:
                    errors.append(f"add action requires '{field}'")
            if has_start != has_end:
                errors.append("add action requires both 'start_time' and 'end_time' or neither")
        else:
            for field in _REQUIRED_FIELDS["add"]:
                if field not in action:
                    errors.append(f"add action requires '{field}'")
    else:
        for field in _REQUIRED_FIELDS[action_type]:
            if field not in action:
                errors.append(f"{action_type} action requires '{field}'")

    has_start = "start_time" in action
    has_end = "end_time" in action
    has_boundary_mode = has_start or has_end
    has_absolute_duration = "duration_minutes" in action
    has_relative_duration = "duration_delta_minutes" in action

    # A resize has exactly one anchor: one or both explicit boundaries, an
    # absolute duration, or a signed duration delta.  Keeping these modes
    # exclusive means the planner is the single owner of all end-time math.
    if action_type == "resize":
        mode_count = sum((has_boundary_mode, has_absolute_duration, has_relative_duration))
        if mode_count != 1:
            errors.append(
                "resize action requires exactly one of boundary times, "
                "'duration_minutes', or 'duration_delta_minutes'"
            )

    # ``duration_minutes`` is valid on a chat untimed add (both time fields
    # absent) or as the sole duration operand of a resize.  It is deliberately
    # not accepted on explicit adds or the other mutation kinds.
    if "duration_minutes" in action:
        is_untimed_chat_add = (
            action_type == "add" and allow_untimed_add and not has_start and not has_end
        )
        is_duration_resize = (
            action_type == "resize" and not has_boundary_mode and not has_relative_duration
        )
        if not (is_untimed_chat_add or is_duration_resize):
            errors.append("duration_minutes is only valid on an untimed add or resize")
        else:
            dm = action["duration_minutes"]
            if not is_plain_int(dm):
                errors.append("duration_minutes must be an integer")
            elif dm <= 0:
                errors.append("duration_minutes must be positive")
            elif dm % GRID_MINUTES:
                errors.append(f"duration_minutes must be a multiple of {GRID_MINUTES}")

    # Relative duration is resize-only.  The value is intentionally signed,
    # but zero is not useful intent and would otherwise create a no-op.
    if has_relative_duration:
        if action_type != "resize":
            errors.append("duration_delta_minutes is only valid on a resize")
        else:
            delta = action["duration_delta_minutes"]
            if not is_plain_int(delta):
                errors.append("duration_delta_minutes must be an integer")
            elif delta == 0:
                errors.append("duration_delta_minutes must be non-zero")
            elif delta % GRID_MINUTES:
                errors.append(f"duration_delta_minutes must be a multiple of {GRID_MINUTES}")

    # ``move`` and ``resize`` only require ``task_id`` structurally, but a
    # payload with no time fields would apply as a silent no-op — the AI
    # would "succeed" without actually doing what the user asked. Reject
    # at the schema layer so the view never sees it.
    if action_type in {"move", "resize"}:
        if action_type == "move" and not has_boundary_mode:
            errors.append("move action requires at least one of 'start_time' or 'end_time'")

    if action_type == "update":
        editable = {"title", "category", "start_time", "end_time"}
        if not editable.intersection(action):
            errors.append(
                "update action requires at least one of 'title', 'category', "
                "'start_time' or 'end_time'"
            )
        if "direction" in action:
            if not isinstance(action["direction"], str) or action["direction"] not in {
                "later",
                "earlier",
                "exact",
            }:
                errors.append("direction must be one of ['earlier', 'exact', 'later']")
            # ``direction`` is placement intent for a TIME change. A
            # metadata-only update carrying ``direction`` but no time field is
            # a meaningless patch — the planner only reads direction alongside
            # a supplied start/end. Reject it at the schema layer.
            elif "start_time" not in action and "end_time" not in action:
                errors.append("direction requires an accompanying 'start_time' or 'end_time'")

    # ``direction`` is only meaningful on an ``update`` (the planner reads
    # ``action.get('direction')`` on updates only). Reject it on any other
    # action type so a move/resize can't silently carry an unvalidated,
    # unhonored direction.
    if action_type != "update" and "direction" in action:
        errors.append(f"'direction' is not valid on a {action_type} action")

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

    if "category" in action and (
        not isinstance(action["category"], str) or action["category"] not in allowed_categories
    ):
        errors.append(f"category must be one of {sorted(allowed_categories)}")

    # For add, both times are required and must form a valid window.
    if (
        action_type == "add"
        and _is_hhmm(action.get("start_time", ""))
        and _is_hhmm(action.get("end_time", ""))
    ):
        start = datetime.datetime.strptime(action["start_time"], "%H:%M").time()
        end = datetime.datetime.strptime(action["end_time"], "%H:%M").time()
        if start >= end:
            errors.append("start_time must be before end_time")

    return errors


def validate_response_envelope(parsed) -> list[str]:
    """Sanity-check the top-level shape before inspecting individual actions.

    Internal helper — after the ``/command/`` endpoint was removed (feature
    0044) there is no user-facing one-shot path; this is now called only by
    ``validate_draft_response``. ``validate_chat_response_envelope``
    re-implements the same checks inline to accommodate the extra ``ask`` field.
    The explanation cap is read from ``settings.LLM_MAX_EXPLANATION_CHARS`` so
    every AI envelope shares a single tunable.
    """
    if not isinstance(parsed, dict):
        return ["response must be a JSON object"]

    errors: list[str] = []
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        errors.append("'actions' must be an array")
    elif len(actions) > MAX_ACTIONS_PER_COMMAND:
        errors.append(f"too many actions ({len(actions)} > {MAX_ACTIONS_PER_COMMAND})")

    explanation = parsed.get("explanation", "")
    if not isinstance(explanation, str):
        errors.append("'explanation' must be a string")
    elif len(explanation) > settings.LLM_MAX_EXPLANATION_CHARS:
        errors.append(f"'explanation' must be <= {settings.LLM_MAX_EXPLANATION_CHARS} chars")

    return errors


def validate_chat_response_envelope(parsed) -> list[str]:
    """Sanity-check the chat-mode response envelope before per-action shape.

    Chat adds an ``ask`` field on top of ``actions`` + ``explanation``. The
    response is mutually exclusive: either commit to actions OR ask one
    clarifying question. Empty actions + null ask is also valid (chit-chat
    / "thanks" turn).

    Caps on ``ask`` and ``explanation`` length live in
    ``settings.LLM_CHAT_MAX_ASK_CHARS`` / ``LLM_MAX_EXPLANATION_CHARS``
    (the latter is shared with the draft envelope so all AI endpoints
    stay aligned).
    """
    if not isinstance(parsed, dict):
        return ["response must be a JSON object"]

    errors: list[str] = []
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        errors.append("'actions' must be an array")
    elif len(actions) > MAX_ACTIONS_PER_COMMAND:
        errors.append(f"too many actions ({len(actions)} > {MAX_ACTIONS_PER_COMMAND})")

    explanation = parsed.get("explanation", "")
    if not isinstance(explanation, str):
        errors.append("'explanation' must be a string")
    elif len(explanation) > settings.LLM_MAX_EXPLANATION_CHARS:
        errors.append(f"'explanation' must be <= {settings.LLM_MAX_EXPLANATION_CHARS} chars")

    if "ask" not in parsed:
        errors.append("'ask' is required (use null when not asking)")
    else:
        ask = parsed["ask"]
        if ask is None:
            pass
        elif not isinstance(ask, str):
            errors.append("'ask' must be a string or null")
        elif ask == "":
            errors.append("'ask' must be null or a non-empty string")
        elif len(ask) > settings.LLM_CHAT_MAX_ASK_CHARS:
            errors.append(f"'ask' must be <= {settings.LLM_CHAT_MAX_ASK_CHARS} chars")

    # Mutually exclusive: ask set ⇒ no actions; actions set ⇒ ask null.
    if isinstance(actions, list) and "ask" in parsed:
        ask = parsed["ask"]
        if isinstance(ask, str) and ask and len(actions) > 0:
            errors.append(
                "'ask' must be null when 'actions' is non-empty (the model "
                "must commit to applying OR asking, never both)"
            )

    return errors


def validate_draft_response(parsed, allowed_categories) -> list[str]:
    """Validate a draft-generation LLM response.

    Same envelope + per-action shape checks as ``validate_response_envelope``
    + ``validate_action_shape``, plus an extra rule: only ``add`` actions
    are valid in a draft (the schedule is empty by construction, so there
    are no ``task_id``s to reference). The cap on action count reuses
    ``MAX_ACTIONS_PER_COMMAND`` — a 20-block day is plausible
    (06:00-23:00 in 50-min slices). Bump only when real drafts need more.
    """
    envelope_errors = validate_response_envelope(parsed)
    if envelope_errors:
        return envelope_errors

    errors: list[str] = []
    for idx, action in enumerate(parsed["actions"]):
        if not isinstance(action, dict):
            errors.append(f"action[{idx}]: must be an object")
            continue
        if action.get("type") != "add":
            errors.append(
                f"action[{idx}]: drafts only accept 'add' actions, got {action.get('type')!r}"
            )
            continue
        per_errs = validate_action_shape(action, allowed_categories)
        if per_errs:
            errors.append(f"action[{idx}]: {', '.join(per_errs)}")
    return errors
