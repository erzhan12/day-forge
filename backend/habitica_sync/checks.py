"""Django system checks for the habitica_sync app.

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
def warn_ineffective_cache_with_habitica_sync(app_configs, **kwargs):
    """Warn when the Habitica task cache uses a non-shared backend in prod.

    Versioned cache keys (see ``cache.tasks_cache_key``) mean a
    per-process cache is **not** a correctness risk: token rotation
    bumps ``account.updated_at`` and every worker computes a fresh key
    on the next read. The cost is purely performance — each gunicorn
    worker (or each request under ``DummyCache``) hits Habitica on its
    first lookup for a given ``(user, date, version)``, multiplying
    baseline Habitica QPS.

    That's a perf/cost concern, not security/correctness, so this is a
    ``Warning`` (not an ``Error`` that would block startup). ``ai.E001``
    stays an ``Error`` because its bypass IS a security issue
    (rate-limit evasion); the Habitica case is not.

    DB-access safety: ``HabiticaAccount.objects.exists()`` raises
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
        from habitica_sync.models import HabiticaAccount
        if not HabiticaAccount.objects.exists():
            return warnings
    except (OperationalError, ProgrammingError):
        # Pre-migrate state: the table doesn't exist yet. Stay silent so
        # ``manage.py migrate`` can run on a fresh database.
        return warnings

    warnings.append(
        Warning(
            f"Habitica task cache uses an ineffective backend ({backend}) "
            "while at least one HabiticaAccount exists. Versioned keys keep "
            "correctness intact, but each worker (or each request, under "
            "DummyCache) will hit Habitica on its first lookup per "
            "(user, date, version) — multiplying baseline Habitica QPS.",
            hint=(
                "Point CACHES['default']['BACKEND'] at a shared cache "
                "(django.core.cache.backends.redis.RedisCache or "
                "django.core.cache.backends.memcached.PyMemcacheCache) "
                "so the cache is shared across workers."
            ),
            id="habitica_sync.W001",
        )
    )
    return warnings


@register()
def error_habitica_secrets_missing_in_production(app_configs, **kwargs):
    """Block production startup when required Habitica secrets are missing.

    Only reads ``settings`` — no DB query — so this is safe to run before
    any migration. A silent fallback to an empty key would silently break
    every token write/read, so a loud ``Error`` is the right shape.

    Also validates the key by instantiating ``Fernet(key)``. Without this
    second check, a malformed key (e.g. wrong length, not base64) would
    pass the "non-empty" gate, the deploy would boot, the first POST
    would crash inside ``set_token`` with ``ImproperlyConfigured``,
    and the user would see a 500 instead of catching the problem at
    startup. ``Fernet(...)`` is pure crypto — no DB or filesystem
    access — so it's safe to run during ``manage.py check``.
    """
    errors = []
    if settings.DEBUG:
        return errors
    key = getattr(settings, "HABITICA_ENCRYPTION_KEY", "") or ""
    client_id = getattr(settings, "HABITICA_CLIENT_ID", "") or ""
    if not key:
        errors.append(
            Error(
                "HABITICA_ENCRYPTION_KEY is not set while DEBUG=False. The "
                "Habitica integration cannot encrypt or decrypt stored "
                "tokens without it; all account writes will fail with "
                "ImproperlyConfigured at request time.",
                hint=(
                    "Generate a key with "
                    "`python -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\"` and set "
                    "HABITICA_ENCRYPTION_KEY in your production environment."
                ),
                id="habitica_sync.E001",
            )
        )
    if not client_id.strip():
        errors.append(
            Error(
                "HABITICA_CLIENT_ID is not set while DEBUG=False. Habitica "
                "requires an x-client header built as "
                "`{HABITICA_CLIENT_ID}-DayForge` for every request.",
                hint=(
                    "Set HABITICA_CLIENT_ID to the maintainer Habitica user "
                    "ID in your production environment."
                ),
                id="habitica_sync.E001",
            )
        )
    if not key:
        return errors

    # Local import so the check module stays import-light when the key
    # is unset (most dev cases).
    from cryptography.fernet import Fernet
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as e:
        errors.append(
            Error(
                "HABITICA_ENCRYPTION_KEY is set but is not a valid Fernet "
                f"key ({type(e).__name__}: {e}). The first POST to "
                "/api/habitica/account/ would crash inside set_token "
                "with ImproperlyConfigured.",
                hint=(
                    "Regenerate the key with "
                    "`python -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\"` and replace "
                    "HABITICA_ENCRYPTION_KEY in your production environment."
                ),
                id="habitica_sync.E001",
            )
        )
    return errors
