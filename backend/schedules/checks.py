"""Django system checks for the schedules app.

These run on ``manage.py check``, ``runserver``, ``migrate``, and other
management commands. We use them to surface deployment gotchas that are
silent at the code level — primarily, the fact that ``select_for_update``
is a no-op on SQLite.
"""

from django.conf import settings
from django.core.checks import Warning, register
from django.db import connections

# Defined locally per module — intentional; each app's checks.py keeps its
# own copy so no app depends on another (see ai/checks.py, todoist_sync, etc.).
_INEFFECTIVE_CACHE_BACKENDS = (
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.filebased.FileBasedCache",
    "django.core.cache.backends.dummy.DummyCache",
)


@register()
def warn_sqlite_in_production(app_configs, **kwargs):
    """Warn when running production-like (DEBUG=False) on SQLite.

    SQLite silently ignores ``SELECT ... FOR UPDATE``, so the locked
    overlap scans in ``schedules.api.create_block``, ``block_detail``,
    ``reorder_blocks``, and ``restore_blocks`` degrade to plain reads.
    A narrow race window then exists between the overlap SELECT and the
    INSERT/UPDATE inside a single user's transaction: two concurrent
    writes against the same schedule can both pass the overlap check
    and create overlapping blocks.

    The check is gated on ``DEBUG=False`` so dev runs stay quiet — the
    race is scoped to a single user's own data and is acceptable for
    development. Production deployments should use PostgreSQL, which
    honors row-level locking and closes the race.
    """
    errors = []
    if settings.DEBUG:
        return errors
    if connections["default"].vendor == "sqlite":
        errors.append(
            Warning(
                "SQLite is configured with DEBUG=False. "
                "select_for_update() is silently ignored on SQLite, so the "
                "overlap checks in schedules.api can race under concurrent "
                "writes against the same user's schedule. Use PostgreSQL "
                "in production to close this gap.",
                hint=(
                    "Switch the default database to PostgreSQL, or accept "
                    "the narrow race window for single-user / low-concurrency "
                    "deployments."
                ),
                id="schedules.W001",
            )
        )
    return errors


@register()
def warn_ineffective_cache_for_connect_rate_limits(app_configs, **kwargs):
    """Warn when the connect rate limits use an ineffective cache backend.

    The per-user connect budgets (``CALDAV_CONNECT_RATE_LIMIT_PER_HOUR``,
    ``TODOIST_CONNECT_RATE_LIMIT_PER_HOUR``,
    ``HABITICA_CONNECT_RATE_LIMIT_PER_HOUR``, feature 0036) count via
    ``schedules.ratelimit.consume_rate_limit`` against
    ``CACHES['default']``. All three flagged backends weaken the
    brute-force protection, but in materially different ways:

    - ``LocMemCache`` — per-process, so each worker enforces its own
      window; the effective budget is roughly ``limit × worker_count``.
      A single-worker deploy is unaffected, but the warning still fires
      for it (Django exposes no worker-count setting to gate on) — on a
      single-worker LocMem box it is purely informational.
    - ``DummyCache`` — stores nothing, so ``cache.add``/``incr`` never
      accumulate; the limiter is **disabled entirely** at *any* worker
      count.
    - ``FileBasedCache`` — shared across workers on one host, but its
      ``incr`` is a non-atomic read-modify-write, so concurrent connect
      attempts can undercount and slip past the budget.

    This is a *security* degradation (not just a cost one, unlike the
    CalDAV/Todoist/Habitica cache-perf warnings), but it stays a
    ``Warning`` rather than an ``Error``: the AI-only ``ai.E001`` boot
    block does not apply here (AI may be disabled), and blocking startup
    on a non-Redis cache would be too aggressive for the LocMem
    single-worker case where the degradation is nil. No DB access:
    unlike the CalDAV/Todoist/Habitica cache warnings (which gate on an
    account row existing), the connect limit applies to any authenticated
    user, so there is no account-existence gate — the check reads only
    settings and is safe to run pre-migrate.
    """
    errors = []
    if settings.DEBUG:
        return errors
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if backend not in _INEFFECTIVE_CACHE_BACKENDS:
        return errors

    errors.append(
        Warning(
            "The connect rate limits use an ineffective cache backend "
            f"({backend}) with DEBUG=False. The per-user "
            "*_CONNECT_RATE_LIMIT_PER_HOUR counters live in "
            "CACHES['default'], which does not enforce the budget "
            "correctly on this backend: LocMemCache is per-process (budget "
            "≈ limit × worker_count, harmless on a single-worker deploy), "
            "DummyCache stores nothing (the limit "
            "is disabled entirely), and FileBasedCache increments "
            "non-atomically (concurrent attempts can undercount) — each "
            "weakens the brute-force protection on the credential-verifying "
            "connect endpoints.",
            hint=(
                "Point CACHES['default']['BACKEND'] at a shared, atomic "
                "cache — django.core.cache.backends.redis.RedisCache (via "
                "REDIS_URL) or "
                "django.core.cache.backends.memcached.PyMemcacheCache — so "
                "the rate-limit counters are enforced cluster-wide."
            ),
            id="schedules.W002",
        )
    )
    return errors
