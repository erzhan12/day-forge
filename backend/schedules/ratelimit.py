"""Shared synchronous fixed-window rate limiting utilities."""

import logging

from django.core.cache import cache
from django.http import JsonResponse

logger = logging.getLogger(__name__)

RATE_LIMIT_WINDOW_SECONDS = 3600
# Bound recovery if an evicted key keeps disappearing between cache operations.
_MAX_RESEED_ATTEMPTS = 3


def consume_rate_limit(key: str, limit: int) -> bool:
    """Consume one token from a fixed-window cache counter.

    The first call anchors the one-hour TTL. Later calls use the cache
    backend's synchronous ``incr`` so Redis increments remain atomic and
    preserve that original expiry. If an entry disappears between ``add``
    and ``incr``, callers race to re-seed with ``add``: one establishes the
    new shared window and the others retry ``incr`` against it. Repeated
    eviction has a bounded retry budget and fails closed.
    """
    if cache.add(key, 1, RATE_LIMIT_WINDOW_SECONDS):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            # The key evicted between add and incr (documented Redis
            # expiry race). Reseeding silently resets the window for this
            # user, so log it — a burst of these is a security-relevant
            # signal, not routine.
            logger.warning(
                "Rate limit key evicted mid-window; reseeding (key=%s)",
                key,
            )
            for _ in range(_MAX_RESEED_ATTEMPTS):
                # Reseeds with a full-window TTL; the original window's remaining
                # TTL is unrecoverable after eviction, so an adversary who forces
                # eviction near window-end gets a fresh window (up to ~2x budget
                # in a targeted attack). Not closable without persisting the
                # original anchor timestamp; accepted trade-off.
                if cache.add(key, 1, RATE_LIMIT_WINDOW_SECONDS):
                    count = 1
                    break

                try:
                    count = cache.incr(key)
                    break
                except ValueError:
                    # The replacement key disappeared before this caller
                    # could join its shared counter. Try to re-seed again.
                    continue
            else:
                # Do not permit credential-verification attempts when the
                # counter cannot be established reliably.
                return False

    if count > limit:
        logger.warning(
            "Rate limit exceeded (key=%s, count=%s, limit=%s)",
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
    response["Retry-After"] = str(RATE_LIMIT_WINDOW_SECONDS)
    return response


def connect_rate_limit_key(provider: str, user_id: int) -> str:
    """Return the namespaced per-provider connection counter key."""
    return f"connect_rl:{provider}:{user_id}"


def category_mutation_rate_limit_key(user_id: int) -> str:
    """Return the namespaced per-user category-mutation counter key.

    One shared counter gates every write on ``/api/user/categories/*``
    (create, update, delete, reorder) so a single budget bounds all
    category churn per user. Reads are never counted.
    """
    return f"category_mutation_rl:{user_id}"
