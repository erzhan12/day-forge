from django.db.backends.signals import connection_created


def _enable_wal_mode(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")


connection_created.connect(_enable_wal_mode)
