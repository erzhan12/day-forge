"""Habitica endpoints."""

import datetime
import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from schedules.http import reject_oversized_body

from habitica_sync import cache as habitica_cache
from habitica_sync import service
from habitica_sync.models import HabiticaAccount
from habitica_sync.schemas import normalized_task_to_dict, validate_account_payload

logger = logging.getLogger(__name__)

_SERVICE_ERROR_STATUS = {
    service.HabiticaAuthError: (401, "Invalid Habitica credentials"),
    service.HabiticaTimeoutError: (504, "Habitica request timed out"),
    service.HabiticaProviderError: (502, "Habitica provider failure"),
}


def _envelope(detail: str, status: int, **extra) -> JsonResponse:
    return JsonResponse({"errors": {"detail": detail, **extra}}, status=status)


def _account_status_payload(account: HabiticaAccount | None) -> dict:
    if account is None:
        return {
            "connected": False,
            "last_verified_at": None,
            "api_user_id": None,
        }
    return {
        "connected": True,
        "last_verified_at": (
            account.last_verified_at.isoformat()
            if account.last_verified_at
            else None
        ),
        "api_user_id": account.api_user_id,
    }


def _service_error_response(exc: Exception) -> JsonResponse:
    for cls, (status, detail) in _SERVICE_ERROR_STATUS.items():
        if isinstance(exc, cls):
            return _envelope(detail, status)
    logger.exception("Unexpected Habitica service error")
    return _envelope("Habitica error", 500)


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def account(request: HttpRequest) -> JsonResponse:
    if request.method == "GET":
        try:
            acc = request.user.habitica_account
        except HabiticaAccount.DoesNotExist:
            acc = None
        return JsonResponse(_account_status_payload(acc))

    if request.method == "DELETE":
        HabiticaAccount.objects.filter(user=request.user).delete()
        return JsonResponse(_account_status_payload(None))

    oversized = reject_oversized_body(request)
    if oversized is not None:
        return oversized
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return _envelope("Invalid JSON.", 400)

    cleaned, errors = validate_account_payload(data)
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    try:
        service.verify_credentials(cleaned["api_user_id"], cleaned["api_token"])
    except service.HabiticaError as e:
        return _service_error_response(e)

    with transaction.atomic():
        acc, _ = HabiticaAccount.objects.select_for_update().get_or_create(
            user=request.user,
        )
        acc.api_user_id = cleaned["api_user_id"]
        acc.set_token(cleaned["api_token"])
        acc.last_verified_at = timezone.now()
        acc.save()

    return JsonResponse(_account_status_payload(acc))


@login_required
@require_http_methods(["GET"])
def tasks(request: HttpRequest, date: str) -> JsonResponse:
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return _envelope("Invalid date format. Use YYYY-MM-DD.", 400)

    try:
        account_row = request.user.habitica_account
    except HabiticaAccount.DoesNotExist:
        return _envelope("No Habitica account configured", 503)

    include_overdue_carryover = request.GET.get("carry_overdue") == "1"
    force_refresh = request.GET.get("refresh") == "1"
    filter_scope = habitica_cache.tasks_filter_scope(
        parsed_date,
        include_overdue_carryover=include_overdue_carryover,
    )

    if not force_refresh:
        cached = habitica_cache.get_cached_tasks(
            account_row,
            parsed_date,
            filter_scope=filter_scope,
        )
        if cached is not None:
            return JsonResponse({"tasks": cached})

    try:
        tasks_list = service.fetch_tasks_for_date(
            account_row,
            parsed_date,
            include_overdue_carryover=include_overdue_carryover,
        )
    except ImproperlyConfigured:
        logger.exception(
            "Habitica decryption misconfigured for user %s", request.user.id
        )
        return _envelope(
            "Habitica service is misconfigured. Contact the administrator.",
            500,
        )
    except service.HabiticaError as e:
        return _service_error_response(e)

    payload = [normalized_task_to_dict(t) for t in tasks_list]
    habitica_cache.set_cached_tasks(
        account_row,
        parsed_date,
        payload,
        filter_scope=filter_scope,
    )
    return JsonResponse({"tasks": payload})


@login_required
@require_http_methods(["POST"])
def complete(request: HttpRequest, task_id: str) -> JsonResponse:
    try:
        account_row = request.user.habitica_account
    except HabiticaAccount.DoesNotExist:
        return _envelope("No Habitica account configured", 503)

    try:
        service.complete_task(account_row, task_id)
    except ImproperlyConfigured:
        logger.exception(
            "Habitica decryption misconfigured for user %s", request.user.id
        )
        return _envelope(
            "Habitica service is misconfigured. Contact the administrator.",
            500,
        )
    except service.HabiticaError as e:
        return _service_error_response(e)

    habitica_cache.invalidate_tasks(account_row)
    return JsonResponse({"ok": True})
