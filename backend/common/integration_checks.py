"""Shared, database-safe system check predicates for integration caches."""

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError

INEFFECTIVE_CACHE_BACKENDS = (
    "django.core.cache.backends.locmem.LocMemCache",
    "django.core.cache.backends.filebased.FileBasedCache",
    "django.core.cache.backends.dummy.DummyCache",
)


def ineffective_cache_with_accounts(model) -> str | None:
    if settings.DEBUG:
        return None
    backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    if backend not in INEFFECTIVE_CACHE_BACKENDS:
        return None
    try:
        return backend if model.objects.exists() else None
    except OperationalError, ProgrammingError:
        # A fresh database has no integration tables during first migrate.
        return None


def invalid_fernet_setting(setting_name: str) -> bool:
    """Validation for E001 checks; never expose the key in diagnostics."""
    from django.core.exceptions import ImproperlyConfigured

    from common.integration_crypto import fernet_for_setting

    try:
        fernet_for_setting(setting_name)
    except ImproperlyConfigured:
        return True
    return False
