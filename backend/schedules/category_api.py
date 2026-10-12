from functools import wraps

from common.http import parse_json_object
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.utils import IntegrityError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from schedules.categories import (
    create_category,
    delete_category,
    ordered_categories,
    serialize_category,
    swap_categories,
    update_category,
)
from schedules.http import parse_swap_body
from schedules.models import Category
from schedules.mutations import ScheduleChanged, schedule_changed_response
from schedules.ratelimit import (
    category_mutation_rate_limit_key,
    consume_rate_limit,
    rate_limited_response,
)


def _error(message, status=400):
    return JsonResponse({"errors": {"category": message}}, status=status)


def _conflict_response(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except ScheduleChanged as exc:
            return schedule_changed_response(exc)

    return wrapped


def _rate_limited(request):
    """Return a 429 response if this user's category-mutation budget is spent, else None."""
    key = category_mutation_rate_limit_key(request.user.id)
    if not consume_rate_limit(key, settings.CATEGORY_MUTATION_RATE_LIMIT_PER_HOUR):
        return rate_limited_response()
    return None


@login_required
@require_http_methods(["GET", "POST"])
@_conflict_response
def categories_collection(request):
    if request.method == "GET":
        return JsonResponse(
            {"categories": [serialize_category(row) for row in ordered_categories(request.user)]}
        )
    limited = _rate_limited(request)
    if limited:
        return limited
    data, err = parse_json_object(request)
    if err:
        return err
    try:
        row = create_category(request.user, data.get("label"), data.get("color_id"))
    except ValueError as exc:
        return _error(str(exc))
    return JsonResponse(serialize_category(row), status=201)


@login_required
@require_http_methods(["PATCH", "DELETE"])
@_conflict_response
def category_detail(request, pk):
    limited = _rate_limited(request)
    if limited:
        return limited
    try:
        category = Category.objects.get(pk=pk, user=request.user)
    except Category.DoesNotExist:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    if request.method == "DELETE":
        try:
            delete_category(request.user, category)
        except Category.DoesNotExist:
            # A concurrent DELETE removed the row between our fetch and the
            # service's in-transaction re-fetch → 404, not a 500.
            return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
        except ValueError as exc:
            return _error(str(exc))
        return JsonResponse({"ok": True})
    data, err = parse_json_object(request)
    if err:
        return err
    try:
        category = update_category(request.user, category, data)
    except Category.DoesNotExist:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    except IntegrityError:
        # Concurrent PATCH of two rows to the same label races the
        # case-insensitive unique label constraint → clean 400, not a 500.
        return _error("A category with that label already exists.")
    except ValueError as exc:
        return _error(str(exc))
    return JsonResponse(serialize_category(category))


@login_required
@require_http_methods(["POST"])
@_conflict_response
def categories_swap(request):
    limited = _rate_limited(request)
    if limited:
        return limited
    parsed = parse_swap_body(request, noun="category")
    if isinstance(parsed, JsonResponse):
        return parsed
    rows = swap_categories(request.user, *parsed)
    if rows is None:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    return JsonResponse({"categories": [serialize_category(row) for row in rows]})
