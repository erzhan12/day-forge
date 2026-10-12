"""Habitica endpoints."""

import datetime
import logging

from common.http import parse_json_object
from common.integration_response import resource_error, resource_meta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from schedules.ratelimit import (
    connect_rate_limit_key,
    consume_rate_limit,
    rate_limited_response,
)
from schedules.window import get_schedule_settings, resolve_time_zone

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
            account.last_verified_at.isoformat() if account.last_verified_at else None
        ),
        "api_user_id": account.api_user_id,
    }


def _service_error_response(
    exc: Exception, *, resource: bool = False, account_state: str = "connected"
) -> JsonResponse:
    for cls, (status, detail) in _SERVICE_ERROR_STATUS.items():
        if isinstance(exc, cls):
            if resource:
                state = (
                    "credentials_error"
                    if status == 401
                    else "unavailable"
                    if status == 504
                    else "provider_error"
                )
                return resource_error(
                    detail, status, account_state=account_state, resource_state=state
                )
            return _envelope(detail, status)
    logger.exception("Unexpected Habitica service error")
    if resource:
        return resource_error(
            "Habitica error",
            500,
            account_state=account_state,
            resource_state="unavailable",
        )
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

    data, err = parse_json_object(request, allow_empty=True, error_field="detail")
    if err is not None:
        return err

    cleaned, errors = validate_account_payload(data)
    if errors:
        return JsonResponse({"errors": errors}, status=400)

    key = connect_rate_limit_key("habitica", request.user.id)
    if not consume_rate_limit(key, settings.HABITICA_CONNECT_RATE_LIMIT_PER_HOUR):
        return rate_limited_response()

    try:
        service.verify_credentials(cleaned["api_user_id"], cleaned["api_token"])
    except service.HabiticaError as e:
        return _service_error_response(
            e,
            resource=True,
            account_state=(
                "connected"
                if HabiticaAccount.objects.filter(user=request.user).exists()
                else "disconnected"
            ),
        )

    try:
        with transaction.atomic():
            acc, _ = HabiticaAccount.objects.select_for_update().get_or_create(
                user=request.user,
            )
            acc.api_user_id = cleaned["api_user_id"]
            acc.set_token(cleaned["api_token"])
            acc.last_verified_at = timezone.now()
            acc.save()
    except ImproperlyConfigured:
        # set_token encrypts, so a missing/malformed HABITICA_ENCRYPTION_KEY
        # surfaces HERE first — the habitica_sync.E001 hint says as much. The
        # tasks and complete views already map this to the config envelope;
        # without the same catch, connect was the one path that leaked a bare
        # 500 instead. Under DEBUG=False that check blocks boot, but a
        # DEBUG=True dev with a bad key hits this directly.
        logger.exception("Habitica encryption misconfigured for user %s", request.user.id)
        return resource_error(
            "Habitica service is misconfigured. Contact the administrator.",
            500,
            account_state="configuration_error",
            resource_state="unavailable",
        )

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
        return resource_error(
            "No Habitica account configured",
            503,
            account_state="disconnected",
            resource_state="unavailable",
        )

    time_zone = get_schedule_settings(request.user).time_zone
    local_today = timezone.localtime(timezone.now(), resolve_time_zone(time_zone)).date()
    force_refresh = request.GET.get("refresh") == "1"
    filter_scope = habitica_cache.tasks_filter_scope(
        parsed_date,
        local_today=local_today,
    )

    if not force_refresh:
        cached = habitica_cache.get_cached_tasks(
            account_row,
            parsed_date,
            time_zone=time_zone,
            filter_scope=filter_scope,
        )
        if cached is not None:
            return JsonResponse({"tasks": cached, "meta": resource_meta("connected", "ready")})

    try:
        tasks_list = service.fetch_tasks_for_date(
            account_row,
            parsed_date,
            local_today=local_today,
        )
    except ImproperlyConfigured:
        logger.exception("Habitica decryption misconfigured for user %s", request.user.id)
        return resource_error(
            "Habitica service is misconfigured. Contact the administrator.",
            500,
            account_state="configuration_error",
            resource_state="unavailable",
        )
    except service.HabiticaError as e:
        return _service_error_response(e, resource=True)

    payload = [normalized_task_to_dict(t) for t in tasks_list]
    habitica_cache.set_cached_tasks(
        account_row,
        parsed_date,
        payload,
        time_zone=time_zone,
        filter_scope=filter_scope,
    )
    return JsonResponse({"tasks": payload, "meta": resource_meta("connected", "ready")})


@login_required
@require_http_methods(["POST"])
def complete(request: HttpRequest, task_id: str) -> JsonResponse:
    try:
        account_row = request.user.habitica_account
    except HabiticaAccount.DoesNotExist:
        return resource_error(
            "No Habitica account configured",
            503,
            account_state="disconnected",
            resource_state="unavailable",
        )

    try:
        service.complete_task(account_row, task_id)
    except ImproperlyConfigured:
        logger.exception("Habitica decryption misconfigured for user %s", request.user.id)
        return resource_error(
            "Habitica service is misconfigured. Contact the administrator.",
            500,
            account_state="configuration_error",
            resource_state="unavailable",
        )
    except service.HabiticaError as e:
        return _service_error_response(e, resource=True)

    habitica_cache.invalidate_tasks(account_row)
    return JsonResponse({"ok": True})
