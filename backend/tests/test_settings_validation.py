"""Import-time behaviour of ``settings.py``.

Covers two things, both pinned by re-executing
``backend/day_forge/settings.py`` under various env values via
``_exec_settings``:

1. ``ANALYTICS_STREAK_*`` validation — the project deliberately raises
   ``ValueError`` at import time (rather than registering a Django system
   check) so a misconfigured deploy fails the worker boot loudly instead
   of silently producing ``streak=0`` forever.
2. ``CACHES['default']`` construction from ``REDIS_URL`` (feature 0015) —
   the ``.strip()`` guard, the ``RedisCache`` branch + ``KEY_PREFIX``, and
   the ``LocMemCache`` fallback. Nothing else in the suite exercises this
   derivation (``test_checks.py`` feeds hand-built ``CACHES`` dicts via
   ``override_settings``; the view tests run under the conftest LocMem
   pin), so a dropped ``.strip()`` or a ``KEY_PREFIX`` typo would
   otherwise pass the whole suite.
"""
from pathlib import Path

import pytest

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "day_forge" / "settings.py"


def _exec_settings(monkeypatch, **env):
    """Execute settings.py in a sandboxed namespace with the given env
    overrides applied. Returns the resulting module-level namespace dict.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    namespace: dict = {"__file__": str(SETTINGS_PATH)}
    code = SETTINGS_PATH.read_text()
    exec(compile(code, str(SETTINGS_PATH), "exec"), namespace)
    return namespace


class TestStreakThresholdValidation:
    def test_valid_default(self, monkeypatch):
        ns = _exec_settings(monkeypatch)
        assert ns["ANALYTICS_STREAK_THRESHOLD"] == 0.8

    def test_valid_explicit(self, monkeypatch):
        ns = _exec_settings(monkeypatch, ANALYTICS_STREAK_THRESHOLD="0.5")
        assert ns["ANALYTICS_STREAK_THRESHOLD"] == 0.5

    def test_valid_boundaries(self, monkeypatch):
        ns_low = _exec_settings(monkeypatch, ANALYTICS_STREAK_THRESHOLD="0.0")
        assert ns_low["ANALYTICS_STREAK_THRESHOLD"] == 0.0
        ns_high = _exec_settings(monkeypatch, ANALYTICS_STREAK_THRESHOLD="1.0")
        assert ns_high["ANALYTICS_STREAK_THRESHOLD"] == 1.0

    def test_above_one_raises(self, monkeypatch):
        with pytest.raises(ValueError, match="ANALYTICS_STREAK_THRESHOLD"):
            _exec_settings(monkeypatch, ANALYTICS_STREAK_THRESHOLD="1.5")

    def test_negative_raises(self, monkeypatch):
        with pytest.raises(ValueError, match="ANALYTICS_STREAK_THRESHOLD"):
            _exec_settings(monkeypatch, ANALYTICS_STREAK_THRESHOLD="-0.1")


class TestStreakWindowValidation:
    def test_valid_default(self, monkeypatch):
        ns = _exec_settings(monkeypatch)
        assert ns["ANALYTICS_STREAK_WINDOW_DAYS"] == 30

    def test_valid_explicit(self, monkeypatch):
        ns = _exec_settings(monkeypatch, ANALYTICS_STREAK_WINDOW_DAYS="14")
        assert ns["ANALYTICS_STREAK_WINDOW_DAYS"] == 14

    def test_zero_raises(self, monkeypatch):
        with pytest.raises(ValueError, match="ANALYTICS_STREAK_WINDOW_DAYS"):
            _exec_settings(monkeypatch, ANALYTICS_STREAK_WINDOW_DAYS="0")

    def test_negative_raises(self, monkeypatch):
        with pytest.raises(ValueError, match="ANALYTICS_STREAK_WINDOW_DAYS"):
            _exec_settings(monkeypatch, ANALYTICS_STREAK_WINDOW_DAYS="-5")


class TestCacheBackendConstruction:
    """Feature 0015: ``CACHES['default']`` is derived from ``REDIS_URL`` at
    import time. ``REDIS_URL`` is set explicitly (incl. to ``""``) in every
    case so ``load_dotenv(override=False)`` cannot let a host ``.env``
    leak in. No live Redis — only the resulting dict is inspected."""

    REDIS = "django.core.cache.backends.redis.RedisCache"
    LOCMEM = "django.core.cache.backends.locmem.LocMemCache"

    def test_redis_url_selects_rediscache_with_prefix(self, monkeypatch):
        ns = _exec_settings(monkeypatch, REDIS_URL="redis://example:6379/0")
        cache = ns["CACHES"]["default"]
        assert cache["BACKEND"] == self.REDIS
        assert cache["LOCATION"] == "redis://example:6379/0"
        assert cache["KEY_PREFIX"] == "dayforge"

    def test_unset_redis_url_falls_back_to_locmem(self, monkeypatch):
        ns = _exec_settings(monkeypatch, REDIS_URL="")
        assert ns["CACHES"]["default"]["BACKEND"] == self.LOCMEM

    def test_whitespace_redis_url_falls_back_to_locmem(self, monkeypatch):
        # A stray-space value must NOT select RedisCache with a blank
        # LOCATION (which would bypass ai.E001 and fail only at first cache
        # hit); .strip() routes it to the LocMem fallback instead.
        ns = _exec_settings(monkeypatch, REDIS_URL="   ")
        assert ns["CACHES"]["default"]["BACKEND"] == self.LOCMEM

    def test_redis_url_is_stripped_in_location(self, monkeypatch):
        ns = _exec_settings(monkeypatch, REDIS_URL="  redis://example:6379/1  ")
        cache = ns["CACHES"]["default"]
        assert cache["BACKEND"] == self.REDIS
        assert cache["LOCATION"] == "redis://example:6379/1"
