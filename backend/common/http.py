"""JSON request parsing with the API's existing error envelopes."""

import json
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, JsonResponse

MAX_REQUEST_BODY_BYTES = 100_000


def reject_oversized_body(
    request: HttpRequest,
    *,
    max_bytes: int = MAX_REQUEST_BODY_BYTES,
    response_factory: Callable[..., JsonResponse] = JsonResponse,
) -> JsonResponse | None:
    """Apply the API's 100 KB cap before decoding the body.

    Django separately enforces DATA_UPLOAD_MAX_MEMORY_SIZE. This smaller
    cap returns the structured 413 response expected by API clients.
    """
    if len(request.body) > max_bytes:
        return response_factory(
            {"errors": {"body": "Request body too large."}}, status=413
        )
    return None


def parse_json_object(
    request: HttpRequest,
    *,
    allow_empty: bool = False,
    max_bytes: int | None = MAX_REQUEST_BODY_BYTES,
    error_field: str = "body",
    response_factory: Callable[..., JsonResponse] = JsonResponse,
) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    """Return an object or an error response, with exactly one set to None.

    Empty bodies are accepted only by review and integration endpoints.
    max_bytes=None lets callers keep a separate size gate before date or
    status checks, or retain login's existing Django body limit. A response
    factory preserves cache headers on preferences and schedule settings.
    """
    if max_bytes is not None:
        error = reject_oversized_body(
            request, max_bytes=max_bytes, response_factory=response_factory
        )
        if error is not None:
            return None, error

    body = request.body
    if allow_empty and body == b"":
        return {}, None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, response_factory(
            {"errors": {error_field: "Invalid JSON."}}, status=400
        )
    if not isinstance(data, dict):
        return None, response_factory(
            {"errors": {error_field: "Request body must be a JSON object."}},
            status=400,
        )
    return data, None
