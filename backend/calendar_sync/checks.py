"""Django system checks for the calendar_sync app.

Runs on every ``manage.py`` invocation (``runserver``, ``check``,
``migrate``). ``E001`` blocks startup; ``W001`` is informational.
"""

from django.conf import settings
from django.core.checks import Error, Warning, register
from django.db.utils import OperationalError, ProgrammingError

_INEFFECTIVE_CACHE_BACKENDS = (
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.filebased.FileBasedCache",
    "django.core.cache.backends.dummy.DummyCache",
)


@register()
def warn_ineffective_cache_with_calendar_sync(app_configs, **kwargs):
    """Warn when the CalDAV event cache uses a non-shared backend in prod.

    Versioned cache keys (see ``cache.events_cache_key``) mean a
    per-process cache is **not** a correctness risk: credential rotation
    bumps ``account.updated_at`` and every worker computes a fresh key
    on the next read. The cost is purely performance — each gunicorn
    worker (or each request under ``DummyCache``) hits iCloud on its
    first lookup for a given ``(user, date, version)``, multiplying
    baseline iCloud QPS.

    That's a perf/cost concern, not security/correctness, so this is a
    ``Warning`` (not an ``Error`` that would block startup). ``ai.E001``
    stays an ``Error`` because its bypass IS a security issue
    (rate-limit evasion); the CalDAV case is not.

    DB-access safety: ``CalDAVAccount.objects.exists()`` raises
    ``OperationalError`` / ``ProgrammingError`` on the first
    ``manage.py migrate`` (the table doesn't exist yet). The
    ``try/except`` is required — without it, ``manage.py migrate``
    cannot run on a fresh database.
    """
    warnings = []
    if settings.DEBUG:
        return warnings
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if backend not in _INEFFECTIVE_CACHE_BACKENDS:
        return warnings

    # Defer the import until the check runs so the app registry is ready.
    try:
        from calendar_sync.models import CalDAVAccount
        if not CalDAVAccount.objects.exists():
            return warnings
    except (OperationalError, ProgrammingError):
        # Pre-migrate state: the table doesn't exist yet. Stay silent so
        # ``manage.py migrate`` can run on a fresh database.
        return warnings

    warnings.append(
        Warning(
            f"CalDAV event cache uses an ineffective backend ({backend}) "
            "while at least one CalDAVAccount exists. Versioned keys keep "
            "correctness intact, but each worker (or each request, under "
            "DummyCache) will hit iCloud on its first lookup per "
            "(user, date, version) — multiplying baseline iCloud QPS.",
            hint=(
                "Point CACHES['default']['BACKEND'] at a shared cache "
                "(django.core.cache.backends.redis.RedisCache or "
                "django.core.cache.backends.memcached.PyMemcacheCache) "
                "so the cache is shared across workers."
            ),
            id="calendar_sync.W001",
        )
    )
    return warnings


@register()
def error_caldav_encryption_key_missing_in_production(app_configs, **kwargs):
    """Block production startup when CALDAV_ENCRYPTION_KEY is unset.

    Only reads ``settings`` — no DB query — so this is safe to run before
    any migration. A silent fallback to an empty key would silently break
    every password write/read, so a loud ``Error`` is the right shape.
    """
    errors = []
    if settings.DEBUG:
        return errors
    key = getattr(settings, "CALDAV_ENCRYPTION_KEY", "") or ""
    if key:
        return errors
    errors.append(
        Error(
            "CALDAV_ENCRYPTION_KEY is not set while DEBUG=False. The "
            "CalDAV integration cannot encrypt or decrypt stored "
            "passwords without it; all account writes will fail with "
            "ImproperlyConfigured at request time.",
            hint=(
                "Generate a key with "
                "`python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\"` and set "
                "CALDAV_ENCRYPTION_KEY in your production environment."
            ),
            id="calendar_sync.E001",
        )
    )
    return errors
