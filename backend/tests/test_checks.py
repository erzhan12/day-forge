"""Tests for the schedules app's system checks."""

from unittest.mock import patch

from ai.checks import error_locmem_cache_with_ai_in_production
from django.test import override_settings
from schedules.checks import warn_sqlite_in_production

LOCMEM = "django.core.cache.backends.locmem.LocMemCache"
REDIS = "django.core.cache.backends.redis.RedisCache"


class TestLocmemCacheProductionError:
    def test_silent_when_debug_true(self):
        """Dev runs ignore LocMem + AI regardless of key status."""
        with override_settings(
            DEBUG=True,
            LLM_API_KEY="sk-test",
            CACHES={"default": {"BACKEND": LOCMEM}},
        ):
            assert error_locmem_cache_with_ai_in_production(app_configs=None) == []

    def test_silent_when_ai_disabled(self):
        """No LLM_API_KEY → no AI traffic → no rate-limit bypass risk."""
        with override_settings(
            DEBUG=False,
            LLM_API_KEY="",
            CACHES={"default": {"BACKEND": LOCMEM}},
        ):
            assert error_locmem_cache_with_ai_in_production(app_configs=None) == []

    def test_silent_on_shared_cache_backend(self):
        """Any non-LocMem backend is presumed shared across workers."""
        with override_settings(
            DEBUG=False,
            LLM_API_KEY="sk-test",
            CACHES={"default": {"BACKEND": REDIS}},
        ):
            assert error_locmem_cache_with_ai_in_production(app_configs=None) == []

    def test_errors_when_prod_plus_locmem_plus_ai(self):
        """DEBUG=False + LLM_API_KEY set + LocMem is the blocking case."""
        with override_settings(
            DEBUG=False,
            LLM_API_KEY="sk-test",
            CACHES={"default": {"BACKEND": LOCMEM}},
        ):
            errors = error_locmem_cache_with_ai_in_production(app_configs=None)
        assert len(errors) == 1
        err = errors[0]
        assert err.id == "ai.E001"
        assert "LocMemCache" in err.msg
        assert "per-process" in err.msg
        assert "Redis" in (err.hint or "")


class TestSqliteProductionWarning:
    def test_silent_when_debug_true(self):
        """In dev mode (DEBUG=True) the check is a no-op even on SQLite."""
        with override_settings(DEBUG=True):
            assert warn_sqlite_in_production(app_configs=None) == []

    def test_warns_when_debug_false_on_sqlite(self):
        """DEBUG=False + SQLite is the production-like footgun we surface."""
        with override_settings(DEBUG=False):
            warnings = warn_sqlite_in_production(app_configs=None)
        assert len(warnings) == 1
        warning = warnings[0]
        assert warning.id == "schedules.W001"
        assert "SQLite" in warning.msg
        assert "select_for_update" in warning.msg

    def test_silent_when_debug_false_on_postgres(self):
        """On non-SQLite vendors the check should not fire."""
        with override_settings(DEBUG=False):
            with patch(
                "schedules.checks.connections"
            ) as mock_connections:
                mock_connections.__getitem__.return_value.vendor = "postgresql"
                warnings = warn_sqlite_in_production(app_configs=None)
        assert warnings == []
