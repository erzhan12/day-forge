"""Django system checks for the AI app.

Run on every ``manage.py`` invocation (``runserver``, ``check``, ``migrate``
…). An ``Error``-level check blocks startup by default, so this is
effectively the ``ImproperlyConfigured`` guard for production deployments
that would otherwise ship with a trivially bypassable per-user rate limit.
"""

from django.conf import settings
from django.core.checks import Error, register


@register()
def error_locmem_cache_with_ai_in_production(app_configs, **kwargs):
    """Block production startup when the AI rate limiter's counter lives
    in a per-process cache.

    ``ai.views._rate_limit_per_user`` stores its fixed-window counter in
    Django's default cache. Under the default ``LocMemCache`` that cache
    is per-worker, so a gunicorn deployment with N workers makes the
    effective limit ``LLM_RATE_LIMIT_PER_HOUR × N`` — trivially bypassed
    by any client whose connections round-robin across workers. Runs
    whenever ``LLM_API_KEY`` is set (AI features actually in use),
    regardless of ``DEBUG`` — a misconfigured prod with ``DEBUG=True``
    would otherwise silently ship the per-worker limiter.
    """
    errors = []
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        return errors
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if backend.endswith(".LocMemCache"):
        errors.append(
            Error(
                "AI rate limiter is configured with LocMemCache while "
                "LLM_API_KEY is set. LocMemCache is per-process, so the "
                "per-user rate limit becomes "
                "LLM_RATE_LIMIT_PER_HOUR × worker_count and can be "
                "bypassed at will.",
                hint=(
                    "Point CACHES['default']['BACKEND'] at a shared cache "
                    "(e.g. django.core.cache.backends.redis.RedisCache or "
                    "django_redis) so the counter is global across workers."
                ),
                id="ai.E001",
            )
        )
    return errors
