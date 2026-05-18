"""REST endpoints for ``Template`` and ``Rule`` CRUD.

Every query is scoped by ``request.user``. Cross-user PK access returns
404 (not 403) to avoid id enumeration — same convention as
``schedules.api.block_detail``.

The unique ``(user, type)`` constraint on ``Template`` is enforced at the
DB layer; both POST and PUT wrap saves in ``transaction.atomic()`` and
catch ``IntegrityError`` to surface a structured 409 instead of a 500.
"""
import datetime
import json
import logging

from ai.prompts import DAY_END, DAY_START
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from schedules.http import (
    VALID_CATEGORIES,
    is_plain_int,
    parse_time_or_error,
    reject_oversized_body,
    validate_five_minute_or_error,
    validate_time_range,
)

from templates_mgr.models import Rule, Template, UserPreferences
from templates_mgr.preferences import get_user_preferences

logger = logging.getLogger(__name__)

MAX_TEMPLATE_NAME_LEN = 100
MAX_TEMPLATE_BLOCKS = 50
MAX_RULE_TEXT_LEN = 500
MAX_RULES_PER_USER = 100
# Bound the priority field to stay well within Django's 32-bit IntegerField
# range so an out-of-range payload returns a structured 400 instead of
# letting the value reach the DB driver and surfacing as a 500. The values
# are far larger than any realistic priority a user would set; the cap
# exists purely to fail fast at the API boundary.
MIN_PRIORITY = -1_000_000
MAX_PRIORITY = 1_000_000

_DAY_START_T = datetime.time.fromisoformat(DAY_START)
_DAY_END_T = datetime.time.fromisoformat(DAY_END)


def _err(field: str, message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"errors": {field: message}}, status=status)


def _template_to_dict(t: Template) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "type": t.type,
        "blocks": list(t.blocks),
    }


def _rule_to_dict(r: Rule) -> dict:
    return {
        "id": r.id,
        "text": r.text,
        "is_active": r.is_active,
        "priority": r.priority,
    }


def validate_template_blocks(blocks) -> list[str]:
    """Validate the ``blocks`` JSON array on a Template.

    Returns a list of error strings. Empty list means OK.

    Checks:
      * ``blocks`` is a list, not too long
      * each entry has ``title`` (string, non-empty, ≤255), ``start_time``,
        ``end_time``, ``category``
      * times parse as HH:MM, sit on a 5-minute grid, fall inside the
        working-day window, and ``start < end``
      * no two entries overlap (half-open intervals)
    """
    if not isinstance(blocks, list):
        return ["blocks must be a list"]
    if len(blocks) > MAX_TEMPLATE_BLOCKS:
        return [f"templates may not contain more than {MAX_TEMPLATE_BLOCKS} blocks"]

    errors: list[str] = []
    parsed: list[tuple[datetime.time, datetime.time, int]] = []

    for i, entry in enumerate(blocks):
        if not isinstance(entry, dict):
            errors.append(f"block[{i}]: must be an object")
            continue
        title = entry.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"block[{i}]: title is required")
        elif len(title) > 255:
            errors.append(f"block[{i}]: title too long")
        category = entry.get("category", "other")
        if category not in VALID_CATEGORIES:
            errors.append(f"block[{i}]: invalid category {category!r}")
        start_str = entry.get("start_time")
        end_str = entry.get("end_time")
        if not isinstance(start_str, str) or not isinstance(end_str, str):
            errors.append(f"block[{i}]: start_time and end_time required (HH:MM)")
            continue
        try:
            start = datetime.datetime.strptime(start_str, "%H:%M").time()
            end = datetime.datetime.strptime(end_str, "%H:%M").time()
        except ValueError:
            errors.append(f"block[{i}]: time format must be HH:MM")
            continue
        if start.minute % 5 != 0 or end.minute % 5 != 0:
            errors.append(f"block[{i}]: times must align to 5-minute granularity")
        if start < _DAY_START_T or end > _DAY_END_T:
            errors.append(
                f"block[{i}]: times must fall within {DAY_START}-{DAY_END}"
            )
        if start >= end:
            errors.append(f"block[{i}]: start_time must be before end_time")
            continue
        parsed.append((start, end, i))

    if not errors:
        # Overlap check on validated entries only — half-open intervals.
        sorted_parsed = sorted(parsed, key=lambda p: p[0])
        for j in range(len(sorted_parsed) - 1):
            s1, e1, _ = sorted_parsed[j]
            s2, _e2, _ = sorted_parsed[j + 1]
            if e1 > s2:
                errors.append("blocks may not overlap")
                break

    return errors


def _parse_template_payload(data) -> tuple[dict, JsonResponse | None]:
    """Validate the create/update body. Returns ``(cleaned, None)`` on
    success, or ``({}, JsonResponse)`` with a 400 on failure."""
    if not isinstance(data, dict):
        return {}, _err("body", "Request body must be a JSON object.")

    name = data.get("name", "")
    if not isinstance(name, str) or not name.strip():
        return {}, _err("name", "Name is required.")
    if len(name) > MAX_TEMPLATE_NAME_LEN:
        return {}, _err(
            "name", f"Name too long (max {MAX_TEMPLATE_NAME_LEN} characters)."
        )

    type_ = data.get("type")
    if type_ not in {Template.Type.WEEKDAY, Template.Type.WEEKEND}:
        return {}, _err("type", "Type must be 'weekday' or 'weekend'.")

    blocks = data.get("blocks", [])
    block_errors = validate_template_blocks(blocks)
    if block_errors:
        return {}, JsonResponse(
            {"errors": {"blocks": block_errors}}, status=400
        )

    return (
        {"name": name.strip(), "type": type_, "blocks": blocks},
        None,
    )


def _parse_rule_create_payload(data) -> tuple[dict, JsonResponse | None]:
    if not isinstance(data, dict):
        return {}, _err("body", "Request body must be a JSON object.")

    text = data.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return {}, _err("text", "Rule text is required.")
    if len(text) > MAX_RULE_TEXT_LEN:
        return {}, _err(
            "text", f"Rule text too long (max {MAX_RULE_TEXT_LEN} characters)."
        )

    cleaned: dict = {"text": text.strip()}
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            return {}, _err("is_active", "is_active must be a boolean.")
        cleaned["is_active"] = data["is_active"]
    if "priority" in data:
        priority = data["priority"]
        if not is_plain_int(priority):
            return {}, _err("priority", "priority must be an integer.")
        if not (MIN_PRIORITY <= priority <= MAX_PRIORITY):
            return {}, _err(
                "priority",
                f"priority must be between {MIN_PRIORITY} and {MAX_PRIORITY}.",
            )
        cleaned["priority"] = priority
    return cleaned, None


def _parse_rule_patch_payload(data) -> tuple[dict, JsonResponse | None]:
    if not isinstance(data, dict):
        return {}, _err("body", "Request body must be a JSON object.")

    cleaned: dict = {}
    if "text" in data:
        text = data["text"]
        if not isinstance(text, str) or not text.strip():
            return {}, _err("text", "Rule text cannot be empty.")
        if len(text) > MAX_RULE_TEXT_LEN:
            return {}, _err(
                "text", f"Rule text too long (max {MAX_RULE_TEXT_LEN} characters)."
            )
        cleaned["text"] = text.strip()
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            return {}, _err("is_active", "is_active must be a boolean.")
        cleaned["is_active"] = data["is_active"]
    if "priority" in data:
        priority = data["priority"]
        if not is_plain_int(priority):
            return {}, _err("priority", "priority must be an integer.")
        if not (MIN_PRIORITY <= priority <= MAX_PRIORITY):
            return {}, _err(
                "priority",
                f"priority must be between {MIN_PRIORITY} and {MAX_PRIORITY}.",
            )
        cleaned["priority"] = priority

    if not cleaned:
        return {}, _err("body", "No editable fields supplied.")
    return cleaned, None


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def templates_collection(request):
    if request.method == "GET":
        items = Template.objects.filter(user=request.user).order_by("type")
        return JsonResponse(
            {"templates": [_template_to_dict(t) for t in items]}
        )

    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _err("body", "Invalid JSON.")

    cleaned, err = _parse_template_payload(data)
    if err is not None:
        return err

    try:
        with transaction.atomic():
            tpl = Template.objects.create(user=request.user, **cleaned)
    except IntegrityError:
        return JsonResponse(
            {
                "errors": {
                    "type": (
                        f"Template for this {cleaned['type']} slot already "
                        f"exists."
                    )
                }
            },
            status=409,
        )
    return JsonResponse(_template_to_dict(tpl), status=201)


@login_required
@require_http_methods(["PUT", "DELETE"])
def template_detail(request, pk):
    try:
        tpl = Template.objects.get(pk=pk, user=request.user)
    except Template.DoesNotExist:
        # 404, not 403, to avoid id enumeration across users.
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)

    if request.method == "DELETE":
        tpl.delete()
        return JsonResponse({"ok": True})

    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _err("body", "Invalid JSON.")

    cleaned, err = _parse_template_payload(data)
    if err is not None:
        return err

    try:
        with transaction.atomic():
            tpl.name = cleaned["name"]
            tpl.type = cleaned["type"]
            tpl.blocks = cleaned["blocks"]
            tpl.save()
    except IntegrityError:
        return JsonResponse(
            {
                "errors": {
                    "type": (
                        f"Template for this {cleaned['type']} slot already "
                        f"exists."
                    )
                }
            },
            status=409,
        )
    return JsonResponse(_template_to_dict(tpl))


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def rules_collection(request):
    if request.method == "GET":
        items = Rule.objects.filter(user=request.user).order_by("-priority", "id")
        return JsonResponse({"rules": [_rule_to_dict(r) for r in items]})

    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _err("body", "Invalid JSON.")

    cleaned, err = _parse_rule_create_payload(data)
    if err is not None:
        return err

    if Rule.objects.filter(user=request.user).count() >= MAX_RULES_PER_USER:
        return _err(
            "rules",
            f"You have reached the maximum of {MAX_RULES_PER_USER} rules.",
            status=400,
        )

    rule = Rule.objects.create(user=request.user, **cleaned)
    return JsonResponse(_rule_to_dict(rule), status=201)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def rule_detail(request, pk):
    try:
        rule = Rule.objects.get(pk=pk, user=request.user)
    except Rule.DoesNotExist:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)

    if request.method == "DELETE":
        rule.delete()
        return JsonResponse({"ok": True})

    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _err("body", "Invalid JSON.")

    cleaned, err = _parse_rule_patch_payload(data)
    if err is not None:
        return err

    for field, value in cleaned.items():
        setattr(rule, field, value)
    rule.save(update_fields=list(cleaned.keys()))
    return JsonResponse(_rule_to_dict(rule))


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------


_VALID_THEMES = frozenset(UserPreferences.Theme.values)


def _prefs_response(payload: dict, status: int = 200) -> JsonResponse:
    """Every response from ``user_preferences`` is per-user state — wrap
    so error and success paths share the same ``Cache-Control`` rule and
    no future edit can accidentally leak a 4xx body through a proxy.

    Spec delta from feature 0010 plan §Phase 2: the plan listed 405 and
    302 in the no-store bullet, but neither response is produced by this
    view. ``@require_http_methods`` returns 405 and ``@login_required``
    returns 302 before any view code runs, so the helper never sees them.
    Practical risk is nil — 405 body is empty and 302 has no body, with
    no per-user state leak surface. Tracked as a 0010-followup in
    ``tasks/todo.md`` so the gap doesn't get lost between releases.
    """
    resp = JsonResponse(payload, status=status)
    resp["Cache-Control"] = "private, no-store"
    return resp


def _prefs_to_dict(prefs: UserPreferences) -> dict:
    """Serialize a ``UserPreferences`` row using the same normalization
    rule as the read-side DTO. Used by ``PATCH`` after a write."""
    from templates_mgr.preferences import normalize_theme

    return {"theme": normalize_theme(prefs.theme)}


@login_required
@require_http_methods(["GET", "PATCH"])
def user_preferences(request):
    """Read or update the authenticated user's UI preferences.

    See feature 0010 plan for the corruption-healing PATCH semantics and
    the ``Cache-Control: private, no-store`` invariant.
    """
    if request.method == "GET":
        prefs = get_user_preferences(request.user)
        return _prefs_response({"theme": prefs.theme})

    oversized = reject_oversized_body(request)
    if oversized is not None:
        # ``reject_oversized_body`` returns a raw 413 JsonResponse; rebuild
        # it through the cache-header helper so the proxy invariant holds.
        return _prefs_response(
            {"errors": {"body": "Request body too large."}}, status=413
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _prefs_response({"errors": {"body": "Invalid JSON."}}, status=400)

    if not isinstance(data, dict):
        return _prefs_response(
            {"errors": {"body": "Request body must be a JSON object."}},
            status=400,
        )

    # Extract recognized fields only (matches the existing PATCH pattern
    # in ``rule_detail``). Unknown keys are silently ignored.
    cleaned: dict = {}
    if "theme" in data:
        theme = data["theme"]
        # `isinstance(theme, str)` guard is load-bearing: `_VALID_THEMES`
        # is a frozenset, so an unhashable value (list, dict) reaches
        # `in` and raises `TypeError`, bypassing this helper and producing
        # an unhandled 500 with no Cache-Control header. Pre-check the
        # type to keep the failure path inside `_prefs_response`.
        if not isinstance(theme, str) or theme not in _VALID_THEMES:
            return _prefs_response(
                {"errors": {"theme": "Invalid theme."}}, status=400
            )
        cleaned["theme"] = theme

    if not cleaned:
        return _prefs_response(
            {"errors": {"body": "No editable fields supplied."}}, status=400
        )

    # Always write recognized fields (no "skip if unchanged" optimization)
    # so that a corrupted ``theme`` row is healed on the next PATCH —
    # the read-side helper normalizes invalid values without writing.
    prefs, _ = UserPreferences.objects.get_or_create(
        user=request.user,
        defaults={"theme": UserPreferences.Theme.CLASSIC},
    )
    for field, value in cleaned.items():
        setattr(prefs, field, value)
    prefs.save(update_fields=list(cleaned.keys()))
    return _prefs_response(_prefs_to_dict(prefs))


# Imports kept at end so unused-import lint doesn't trip on
# ``parse_time_or_error`` / ``validate_five_minute_or_error`` /
# ``validate_time_range`` — they are intentionally re-exported for tests
# and consistency with ``schedules.api`` even when not directly called
# above (the validation is inlined here for richer per-block errors).
__all__ = [
    "templates_collection",
    "template_detail",
    "rules_collection",
    "rule_detail",
    "user_preferences",
    "validate_template_blocks",
    "parse_time_or_error",
    "validate_five_minute_or_error",
    "validate_time_range",
]
