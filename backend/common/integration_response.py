"""Explicit integration resource state, independent of HTTP transport status."""

from django.http import JsonResponse


def resource_meta(account_state: str, resource_state: str) -> dict[str, str]:
    return {"account_state": account_state, "resource_state": resource_state}


def resource_error(
    detail: str,
    status: int,
    *,
    account_state: str,
    resource_state: str,
) -> JsonResponse:
    code = {
        "disconnected": "integration_account_missing",
        "configuration_error": "integration_configuration_error",
        "credentials_error": "integration_credentials_error",
        "provider_error": "integration_provider_error",
        "unavailable": "integration_unavailable",
    }.get(resource_state, "integration_error")
    if account_state == "disconnected" and status == 503:
        code = "integration_account_missing"
    elif account_state == "configuration_error":
        code = "integration_configuration_error"
    return JsonResponse(
        {
            "errors": {"detail": detail},
            "code": code,
            "meta": resource_meta(account_state, resource_state),
        },
        status=status,
    )
