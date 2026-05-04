"""Import-time validation of analytics env vars.

The project deliberately raises ``ValueError`` at import time (rather
than registering a Django system check) for ``ANALYTICS_STREAK_*`` so a
misconfigured deploy fails the worker boot loudly instead of silently
producing ``streak=0`` forever. These tests pin that contract by
re-executing ``backend/day_forge/settings.py`` under various env values.
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
