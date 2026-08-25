import json

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
from schedules.http import parse_swap_body, reject_oversized_body
from schedules.models import Category


def _error(message, status=400):
    return JsonResponse({"errors": {"category": message}}, status=status)


def _body(request):
    oversized = reject_oversized_body(request)
    if oversized:
        return None, oversized
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return None, JsonResponse({"errors": {"body": "Invalid JSON."}}, status=400)
    if not isinstance(data, dict):
        return None, JsonResponse(
            {"errors": {"body": "Request body must be a JSON object."}}, status=400
        )
    return data, None


@login_required
@require_http_methods(["GET", "POST"])
def categories_collection(request):
    if request.method == "GET":
        return JsonResponse(
            {"categories": [serialize_category(row) for row in ordered_categories(request.user)]}
        )
    data, err = _body(request)
    if err:
        return err
    try:
        row = create_category(request.user, data.get("label"), data.get("color_id"))
    except ValueError as exc:
        return _error(str(exc))
    return JsonResponse(serialize_category(row), status=201)


@login_required
@require_http_methods(["PATCH", "DELETE"])
def category_detail(request, pk):
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
    data, err = _body(request)
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
def categories_swap(request):
    parsed = parse_swap_body(request, noun="category")
    if isinstance(parsed, JsonResponse):
        return parsed
    rows = swap_categories(request.user, *parsed)
    if rows is None:
        return JsonResponse({"errors": {"detail": "Not found."}}, status=404)
    return JsonResponse({"categories": [serialize_category(row) for row in rows]})
