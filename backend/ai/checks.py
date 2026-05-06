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


@register()
def error_draft_capture_in_production(app_configs, **kwargs):
    """Block production startup when LLM_DRAFT_CAPTURE_PROMPT_PATH is
    set under DEBUG=False.

    The capture writes the rendered LLM user_message — which embeds the
    user's full ``LLM_HISTORY_DAYS`` of past schedules and their template
    — to disk on every ``generate-draft`` call. That's pure test
    infrastructure (see Phase 6 Test 7), and any non-dev deployment with
    it set is almost certainly a misconfiguration that would silently
    spool user PII to a local file. Mirrors the ``ai.E001`` pattern.
    """
    errors = []
    if not getattr(settings, "LLM_DRAFT_CAPTURE_PROMPT_PATH", ""):
        return errors
    if settings.DEBUG:
        return errors
    errors.append(
        Error(
            "LLM_DRAFT_CAPTURE_PROMPT_PATH is set while DEBUG=False. "
            "The capture writes the user's full schedule history (PII) "
            "to disk on every draft request — test infrastructure only, "
            "never safe in production.",
            hint=(
                "Unset LLM_DRAFT_CAPTURE_PROMPT_PATH in your environment "
                "(or remove it from .env) before running with DEBUG=False."
            ),
            id="ai.E002",
        )
    )
    return errors
