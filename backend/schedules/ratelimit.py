"""Shared synchronous fixed-window rate limiting utilities."""

import logging

from django.core.cache import cache
from django.http import JsonResponse

logger = logging.getLogger(__name__)

CONNECT_RATE_LIMIT_WINDOW_SECONDS = 3600


def consume_rate_limit(key: str, limit: int) -> bool:
    """Consume one token from a fixed-window cache counter.

    The first call anchors the one-hour TTL. Later calls use the cache
    backend's synchronous ``incr`` so Redis increments remain atomic and
    preserve that original expiry. If an entry disappears between ``add``
    and ``incr``, re-seed a fresh fixed window.
    """
    if cache.add(key, 1, CONNECT_RATE_LIMIT_WINDOW_SECONDS):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, CONNECT_RATE_LIMIT_WINDOW_SECONDS)
            count = 1

    if count > limit:
        logger.warning(
            "Connect rate limit exceeded (key=%s, count=%s, limit=%s)",
            key,
            count,
            limit,
        )
        return False
    return True


def rate_limited_response() -> JsonResponse:
    """Return the standard JSON error envelope for an exhausted budget."""
    response = JsonResponse(
        {"errors": {"detail": "Rate limit exceeded. Try again later."}},
        status=429,
    )
    # RFC 6585 §4: a 429 SHOULD advertise when to retry. The window is a
    # fixed constant, so the worst-case wait is one full window.
    response["Retry-After"] = str(CONNECT_RATE_LIMIT_WINDOW_SECONDS)
    return response


def connect_rate_limit_key(provider: str, user_id: int) -> str:
    """Return the namespaced per-provider connection counter key."""
    return f"connect_rl:{provider}:{user_id}"
