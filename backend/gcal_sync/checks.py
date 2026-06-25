"""Django system checks for the gcal_sync app.

Runs on every ``manage.py`` invocation (``runserver``, ``check``,
``migrate``). ``E001`` blocks startup; ``W001`` is informational.

Unlike CalDAV (whose ``E001`` covers only the encryption key), ``gcal_sync.
E001`` makes **all four** ``GOOGLE_OAUTH_*`` vars a hard boot dependency for
every ``DEBUG=False`` deploy — even if no user has connected Google. An
optional-Google staging env must set all four or stay ``DEBUG=True``.
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
def warn_ineffective_cache_with_gcal_sync(app_configs, **kwargs):
    """Warn when the Google event cache uses a non-shared backend in prod.

    Versioned cache keys (see ``cache.events_cache_key``) keep correctness
    intact regardless of backend — token rotation bumps
    ``account.updated_at`` and every worker computes a fresh key. The cost
    is purely performance (each worker hits Google once per
    ``(user, account, date, version)`` on first lookup), so this is a
    ``Warning`` not a startup-blocking ``Error``.

    DB-access safety: the ``exists()`` probe raises ``OperationalError`` /
    ``ProgrammingError`` on the first ``manage.py migrate`` (table absent).
    The ``try/except`` is required so a fresh DB can migrate.
    """
    warnings = []
    if settings.DEBUG:
        return warnings
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if backend not in _INEFFECTIVE_CACHE_BACKENDS:
        return warnings

    try:
        from gcal_sync.models import GoogleCalendarAccount
        if not GoogleCalendarAccount.objects.exists():
            return warnings
    except (OperationalError, ProgrammingError):
        return warnings

    warnings.append(
        Warning(
            f"Google Calendar event cache uses an ineffective backend "
            f"({backend}) while at least one GoogleCalendarAccount exists. "
            "Versioned keys keep correctness intact, but each worker will "
            "hit Google on its first lookup per (user, account, date, "
            "version) — multiplying baseline Google QPS.",
            hint=(
                "Point CACHES['default']['BACKEND'] at a shared cache "
                "(django.core.cache.backends.redis.RedisCache or "
                "django.core.cache.backends.memcached.PyMemcacheCache) "
                "so the cache is shared across workers."
            ),
            id="gcal_sync.W001",
        )
    )
    return warnings


@register()
def error_google_oauth_config_missing_in_production(app_configs, **kwargs):
    """Block production startup when the token key OR any OAuth client var is
    missing/malformed.

    Settings-only (no DB query) so it's safe to run before any migration.
    Emits a distinct, actionable message per missing var. The token key is
    additionally validated by instantiating ``Fernet(key)`` so a malformed
    key fails at startup rather than on the first events fetch.
    """
    errors = []
    if settings.DEBUG:
        return errors

    # Required OAuth client config (a hard boot dependency in production).
    for name in (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
    ):
        if not (getattr(settings, name, "") or ""):
            errors.append(
                Error(
                    f"{name} is not set while DEBUG=False. The Google "
                    "Calendar OAuth flow cannot run without it.",
                    hint=(
                        "Set all four GOOGLE_OAUTH_* vars (client id, client "
                        "secret, redirect uri, token key) from the Google "
                        "Cloud console OAuth-client setup, or run DEBUG=True "
                        "for a Google-less env."
                    ),
                    id="gcal_sync.E001",
                )
            )

    key = getattr(settings, "GOOGLE_OAUTH_TOKEN_KEY", "") or ""
    if not key:
        errors.append(
            Error(
                "GOOGLE_OAUTH_TOKEN_KEY is not set while DEBUG=False. The "
                "Google integration cannot encrypt or decrypt stored tokens "
                "without it; all token writes will fail with "
                "ImproperlyConfigured at request time.",
                hint=(
                    "Generate a key with "
                    "`python -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\"` and set "
                    "GOOGLE_OAUTH_TOKEN_KEY in your production environment."
                ),
                id="gcal_sync.E001",
            )
        )
        return errors

    from cryptography.fernet import Fernet
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as e:
        errors.append(
            Error(
                "GOOGLE_OAUTH_TOKEN_KEY is set but is not a valid Fernet key "
                f"({type(e).__name__}: {e}). The first Google token write "
                "would crash with ImproperlyConfigured.",
                hint=(
                    "Regenerate the key with "
                    "`python -c \"from cryptography.fernet import Fernet; "
                    "print(Fernet.generate_key().decode())\"` and replace "
                    "GOOGLE_OAUTH_TOKEN_KEY in your production environment."
                ),
                id="gcal_sync.E001",
            )
        )
    return errors
