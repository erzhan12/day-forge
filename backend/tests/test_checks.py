"""Tests for the schedules app's system checks."""

from unittest.mock import patch

from django.test import override_settings
from schedules.checks import warn_sqlite_in_production


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
