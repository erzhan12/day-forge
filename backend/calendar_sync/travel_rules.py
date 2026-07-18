"""REST endpoints for ``TravelRule`` CRUD (feature 0026).

Every query is scoped by ``request.user``. Cross-user PK access returns
404 (not 403) to avoid id enumeration — same convention as
``schedules.api.block_detail`` and ``templates_mgr.api.rule_detail``.

Validation mirrors ``templates_mgr.api._parse_rule_create_payload`` /
``_parse_rule_patch_payload``.
"""
import json

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from schedules.http import VALID_CATEGORIES, is_plain_int, reject_oversized_body

from calendar_sync.models import TravelRule

MAX_KEYWORD_LEN = 100
MAX_TRAVEL_MINUTES = 600
MAX_TRAVEL_RULES_PER_USER = 100
# Same rationale as templates_mgr.api.MIN_PRIORITY/MAX_PRIORITY: fail fast
# at the API boundary well inside the 32-bit IntegerField range.
MIN_ORDER = -1_000_000
MAX_ORDER = 1_000_000


def _err(field: str, message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"errors": {field: message}}, status=status)


def _rule_to_dict(r: TravelRule) -> dict:
    return {
        "id": r.id,
        "keyword": r.keyword,
        "travel_there_minutes": r.travel_there_minutes,
        "travel_back_minutes": r.travel_back_minutes,
        "category": r.category,
        "order": r.order,
    }


def _clean_keyword(value) -> tuple[str | None, JsonResponse | None]:
    if not isinstance(value, str) or not value.strip():
        return None, _err("keyword", "Keyword is required.")
    keyword = value.strip()
    if len(keyword) > MAX_KEYWORD_LEN:
        return None, _err(
            "keyword", f"Keyword too long (max {MAX_KEYWORD_LEN} characters)."
        )
    return keyword, None


def _clean_minutes(field: str, value) -> tuple[int | None, JsonResponse | None]:
    if not is_plain_int(value):
        return None, _err(field, f"{field} must be an integer.")
    if not (0 <= value <= MAX_TRAVEL_MINUTES):
        return None, _err(
            field, f"{field} must be between 0 and {MAX_TRAVEL_MINUTES}."
        )
    return value, None


def _clean_category(value) -> tuple[str | None, JsonResponse | None]:
    # "" means "no override"; the created block defaults to "other".
    # `isinstance` guard first — an unhashable value would raise TypeError
    # on the `in`-set check (same footgun as user_preferences.theme).
    if not isinstance(value, str) or (value != "" and value not in VALID_CATEGORIES):
        choices = ", ".join(sorted(VALID_CATEGORIES))
        return None, _err(
            "category", f'Invalid category. Choose from: {choices}, or "".'
        )
    return value, None


def _clean_order(value) -> tuple[int | None, JsonResponse | None]:
    if not is_plain_int(value):
        return None, _err("order", "order must be an integer.")
    if not (MIN_ORDER <= value <= MAX_ORDER):
        return None, _err(
            "order", f"order must be between {MIN_ORDER} and {MAX_ORDER}."
        )
    return value, None


def _parse_create_payload(data) -> tuple[dict, JsonResponse | None]:
    if not isinstance(data, dict):
        return {}, _err("body", "Request body must be a JSON object.")

    keyword, err = _clean_keyword(data.get("keyword"))
    if err is not None:
        return {}, err
    cleaned: dict = {"keyword": keyword}

    for field in ("travel_there_minutes", "travel_back_minutes"):
        if field in data:
            value, err = _clean_minutes(field, data[field])
            if err is not None:
                return {}, err
            cleaned[field] = value
    if "category" in data:
        value, err = _clean_category(data["category"])
        if err is not None:
            return {}, err
        cleaned["category"] = value
    if "order" in data:
        value, err = _clean_order(data["order"])
        if err is not None:
            return {}, err
        cleaned["order"] = value
    return cleaned, None


def _parse_patch_payload(data) -> tuple[dict, JsonResponse | None]:
    if not isinstance(data, dict):
        return {}, _err("body", "Request body must be a JSON object.")

    cleaned: dict = {}
    if "keyword" in data:
        keyword, err = _clean_keyword(data["keyword"])
        if err is not None:
            return {}, err
        cleaned["keyword"] = keyword
    for field in ("travel_there_minutes", "travel_back_minutes"):
        if field in data:
            value, err = _clean_minutes(field, data[field])
            if err is not None:
                return {}, err
            cleaned[field] = value
    if "category" in data:
        value, err = _clean_category(data["category"])
        if err is not None:
            return {}, err
        cleaned["category"] = value
    if "order" in data:
        value, err = _clean_order(data["order"])
        if err is not None:
            return {}, err
        cleaned["order"] = value

    if not cleaned:
        return {}, _err("body", "No editable fields supplied.")
    return cleaned, None


@login_required
@require_http_methods(["GET", "POST"])
def travel_rules_collection(request):
    if request.method == "GET":
        items = TravelRule.objects.filter(user=request.user).order_by("order", "id")
        return JsonResponse({"travel_rules": [_rule_to_dict(r) for r in items]})

    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return _err("body", "Invalid JSON.")

    cleaned, err = _parse_create_payload(data)
    if err is not None:
        return err

    if (
        TravelRule.objects.filter(user=request.user).count()
        >= MAX_TRAVEL_RULES_PER_USER
    ):
        return _err(
            "travel_rules",
            f"You have reached the maximum of {MAX_TRAVEL_RULES_PER_USER} "
            f"travel rules.",
        )

    if "order" not in cleaned:
        # Born-distinct order: with a bare default=0 every new rule would
        # tie at 0 and the swap-based reorder in TravelRulesList.vue would
        # be a no-op between equal values.
        max_order = TravelRule.objects.filter(user=request.user).aggregate(
            Max("order")
        )["order__max"]
        cleaned["order"] = 0 if max_order is None else max_order + 1

    rule = TravelRule.objects.create(user=request.user, **cleaned)
    return JsonResponse(_rule_to_dict(rule), status=201)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def travel_rule_detail(request, pk):
    try:
        rule = TravelRule.objects.get(pk=pk, user=request.user)
    except TravelRule.DoesNotExist:
        # 404, not 403, to avoid id enumeration across users.
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

    cleaned, err = _parse_patch_payload(data)
    if err is not None:
        return err

    for field, value in cleaned.items():
        setattr(rule, field, value)
    rule.save(update_fields=[*cleaned.keys(), "updated_at"])
    return JsonResponse(_rule_to_dict(rule))
