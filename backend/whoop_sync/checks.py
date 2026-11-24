"""Django system checks for the whoop_sync app (feature 0107).

Unlike ``gcal_sync.E001``, WHOOP is not a boot dependency: with no
``WHOOP_OAUTH_*`` value set the integration is disabled and every check
passes. Once any value is set, ``E001`` requires all four and a valid
Fernet key, in every ``DEBUG`` mode. Settings-only, so it is safe before
any migration.
"""

from common.integration_checks import ineffective_cache_with_accounts, invalid_fernet_setting
from django.conf import settings
from django.core.checks import Error, Warning, register

WHOOP_OAUTH_SETTINGS = (
    "WHOOP_OAUTH_CLIENT_ID",
    "WHOOP_OAUTH_CLIENT_SECRET",
    "WHOOP_OAUTH_REDIRECT_URI",
    "WHOOP_OAUTH_TOKEN_KEY",
)

_HINT = (
    "Set all four WHOOP_OAUTH_* vars (client id, client secret, redirect uri, "
    "token key) or none of them to keep WHOOP disabled."
)


@register()
def error_whoop_oauth_partial_config(app_configs, **kwargs):
    present = {name: bool(getattr(settings, name, "") or "") for name in WHOOP_OAUTH_SETTINGS}
    if not any(present.values()):
        return []
    errors = [
        Error(
            f"{name} is not set while other WHOOP_OAUTH_* settings are.",
            hint=_HINT,
            id="whoop_sync.E001",
        )
        for name, is_set in present.items()
        if not is_set
    ]
    if present["WHOOP_OAUTH_TOKEN_KEY"] and invalid_fernet_setting("WHOOP_OAUTH_TOKEN_KEY"):
        errors.append(
            Error(
                "WHOOP_OAUTH_TOKEN_KEY is set but is not a valid Fernet key.",
                hint=(
                    "Generate a key with "
                    '`python -c "from cryptography.fernet import Fernet; '
                    'print(Fernet.generate_key().decode())"`.'
                ),
                id="whoop_sync.E001",
            )
        )
    return errors


@register()
def warn_ineffective_cache_with_whoop_sync(app_configs, **kwargs):
    """Warn when the single-flight refresh lock cannot be shared across workers.

    WHOOP rotates the refresh token and rejects concurrent refreshes, so the
    ``whoop_refresh:<account_id>`` lock must live in a shared cache (Redis in
    production). A per-process backend lets two workers refresh at once.
    """
    from whoop_sync.models import WhoopAccount

    backend = ineffective_cache_with_accounts(WhoopAccount)
    if backend is None:
        return []
    return [
        Warning(
            f"WHOOP refresh lock uses a non-shared cache backend ({backend}) while "
            "a WhoopAccount exists. Concurrent refreshes in different workers can "
            "invalidate the rotated refresh token and force a reconnect.",
            hint="Point CACHES['default'] at Redis (set REDIS_URL).",
            id="whoop_sync.W001",
        )
    ]
