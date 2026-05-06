"""Tests for the schedules app's system checks."""

from unittest.mock import patch

from ai.checks import (
    error_draft_capture_in_production,
    error_locmem_cache_with_ai_in_production,
)
from django.test import override_settings
from schedules.checks import warn_sqlite_in_production

LOCMEM = "django.core.cache.backends.locmem.LocMemCache"
REDIS = "django.core.cache.backends.redis.RedisCache"


class TestLocmemCacheProductionError:
    def test_fires_even_when_debug_true(self):
        """A misconfigured prod with DEBUG=True must not silently bypass
        the rate-limiter check; AI-enabled + LocMem fires regardless of
        DEBUG mode."""
        with override_settings(
            DEBUG=True,
            LLM_API_KEY="sk-test",
            CACHES={"default": {"BACKEND": LOCMEM}},
        ):
            errors = error_locmem_cache_with_ai_in_production(app_configs=None)
        assert len(errors) == 1
        assert errors[0].id == "ai.E001"

    def test_silent_when_ai_disabled(self):
        """No LLM_API_KEY → no AI traffic → no rate-limit bypass risk."""
        with override_settings(
            DEBUG=False,
            LLM_API_KEY="",
            CACHES={"default": {"BACKEND": LOCMEM}},
        ):
            assert error_locmem_cache_with_ai_in_production(app_configs=None) == []

    def test_silent_when_api_key_is_whitespace(self):
        """A whitespace-only key is effectively unset — don't false-alarm."""
        with override_settings(
            DEBUG=False,
            LLM_API_KEY="   ",
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


class TestDraftCaptureProductionError:
    def test_silent_when_path_unset(self):
        """Default-off — no error when LLM_DRAFT_CAPTURE_PROMPT_PATH is empty."""
        with override_settings(DEBUG=False, LLM_DRAFT_CAPTURE_PROMPT_PATH=""):
            assert error_draft_capture_in_production(app_configs=None) == []

    def test_silent_when_debug_true(self):
        """Dev mode + path set is the intended testing flow — no error."""
        with override_settings(
            DEBUG=True,
            LLM_DRAFT_CAPTURE_PROMPT_PATH="/tmp/draft_prompt_test7.txt",
        ):
            assert error_draft_capture_in_production(app_configs=None) == []

    def test_errors_when_prod_with_path_set(self):
        """DEBUG=False + path set = blocking. The msg / hint must name
        the env var so the operator can resolve without spelunking."""
        with override_settings(
            DEBUG=False,
            LLM_DRAFT_CAPTURE_PROMPT_PATH="/tmp/draft_prompt_test7.txt",
        ):
            errors = error_draft_capture_in_production(app_configs=None)
        assert len(errors) == 1
        err = errors[0]
        assert err.id == "ai.E002"
        assert "LLM_DRAFT_CAPTURE_PROMPT_PATH" in err.msg
        assert "DEBUG=False" in err.msg
        assert "LLM_DRAFT_CAPTURE_PROMPT_PATH" in (err.hint or "")


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
