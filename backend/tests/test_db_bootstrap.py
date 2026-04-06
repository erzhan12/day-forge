from unittest.mock import MagicMock

from day_forge import _enable_wal_mode


class TestEnableWalMode:
    def test_executes_pragmas_on_sqlite(self):
        cursor = MagicMock()
        conn = MagicMock(vendor="sqlite")
        conn.cursor.return_value = cursor

        _enable_wal_mode(sender=None, connection=conn)

        cursor.execute.assert_any_call("PRAGMA journal_mode=WAL;")
        cursor.execute.assert_any_call("PRAGMA foreign_keys=ON;")
        assert cursor.execute.call_count == 2

    def test_skips_non_sqlite(self):
        cursor = MagicMock()
        conn = MagicMock(vendor="postgresql")
        conn.cursor.return_value = cursor

        _enable_wal_mode(sender=None, connection=conn)

        cursor.execute.assert_not_called()
