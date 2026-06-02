"""Django system checks for the AI app.

Run on every ``manage.py`` invocation (``runserver``, ``check``, ``migrate``
…). An ``Error``-level check blocks startup by default, so this is
effectively the ``ImproperlyConfigured`` guard for production deployments
that would otherwise ship with a trivially bypassable per-user rate limit.
"""

from django.conf import settings
from django.core.checks import Error, register

# Cache backends that cannot back a correct cross-worker rate limiter.
# LocMemCache and DummyCache are per-process (each worker has its own
# store, or no store at all); FileBasedCache is shared on disk but its
# ``incr`` is not an atomic cross-worker counter (per-file locks are not
# Redis ``INCR``). Any of them makes ``ai.views._consume_rate_limit``
# under-count, multiplying the effective per-user limit. Mirrors
# ``calendar_sync.checks._INEFFECTIVE_CACHE_BACKENDS`` — defined locally
# rather than cross-imported to avoid an app-to-app dependency.
_INEFFECTIVE_CACHE_BACKENDS = (
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.filebased.FileBasedCache",
    "django.core.cache.backends.dummy.DummyCache",
)


@register()
def error_locmem_cache_with_ai_in_production(app_configs, **kwargs):
    """Block startup when the AI rate-limit counters live in a cache
    backend that can't enforce a correct cross-worker limit.

    All three AI rate-limit buckets — ``ai_cmd_rl`` (one-shot command,
    ``LLM_RATE_LIMIT_PER_HOUR``), ``ai_draft_rl`` (auto/manual draft,
    ``LLM_DRAFT_RATE_LIMIT_PER_HOUR``), and ``ai_chat_rl`` (multi-turn
    chat, ``LLM_CHAT_RATE_LIMIT_PER_HOUR``) — share ``CACHES['default']``
    via ``ai.views._consume_rate_limit``. An ineffective backend
    (``LocMemCache`` / ``DummyCache`` are per-process; ``FileBasedCache``
    has no atomic cross-worker ``incr``) makes the effective limit on
    EACH bucket ``configured_limit × worker_count`` — trivially bypassed
    by any client whose connections round-robin across workers. Genuinely
    shared, atomic backends (``RedisCache`` via ``REDIS_URL``,
    ``PyMemcacheCache``) pass. Runs whenever ``LLM_API_KEY`` is set (AI
    features actually in use), regardless of ``DEBUG`` — a misconfigured
    prod with ``DEBUG=True`` would otherwise silently ship the broken
    limiter.
    """
    errors = []
    if not settings.LLM_API_KEY or not settings.LLM_API_KEY.strip():
        return errors
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if backend in _INEFFECTIVE_CACHE_BACKENDS:
        errors.append(
            Error(
                "AI rate limiters (ai_cmd_rl / ai_draft_rl / ai_chat_rl) "
                f"are configured with an ineffective cache backend ({backend}) "
                "while LLM_API_KEY is set. LocMemCache and DummyCache are "
                "per-process; FileBasedCache has no atomic cross-worker incr. "
                "On any of them each bucket's effective limit becomes its "
                "configured value × worker_count and can be bypassed at will.",
                hint=(
                    "Point CACHES['default']['BACKEND'] at a shared, atomic "
                    "cache (django.core.cache.backends.redis.RedisCache via "
                    "REDIS_URL, or PyMemcacheCache) so all three counters are "
                    "global and atomic across workers."
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
