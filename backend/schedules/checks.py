"""Django system checks for the schedules app.

These run on ``manage.py check``, ``runserver``, ``migrate``, and other
management commands. We use them to surface deployment gotchas that are
silent at the code level — primarily, the fact that ``select_for_update``
is a no-op on SQLite.
"""

from django.conf import settings
from django.core.checks import Warning, register
from django.db import connections


@register()
def warn_sqlite_in_production(app_configs, **kwargs):
    """Warn when running production-like (DEBUG=False) on SQLite.

    SQLite silently ignores ``SELECT ... FOR UPDATE``, so the locked
    overlap scans in ``schedules.api.create_block``, ``block_detail``,
    ``reorder_blocks``, and ``restore_blocks`` degrade to plain reads.
    A narrow race window then exists between the overlap SELECT and the
    INSERT/UPDATE inside a single user's transaction: two concurrent
    writes against the same schedule can both pass the overlap check
    and create overlapping blocks.

    The check is gated on ``DEBUG=False`` so dev runs stay quiet — the
    race is scoped to a single user's own data and is acceptable for
    development. Production deployments should use PostgreSQL, which
    honors row-level locking and closes the race.
    """
    errors = []
    if settings.DEBUG:
        return errors
    if connections["default"].vendor == "sqlite":
        errors.append(
            Warning(
                "SQLite is configured with DEBUG=False. "
                "select_for_update() is silently ignored on SQLite, so the "
                "overlap checks in schedules.api can race under concurrent "
                "writes against the same user's schedule. Use PostgreSQL "
                "in production to close this gap.",
                hint=(
                    "Switch the default database to PostgreSQL, or accept "
                    "the narrow race window for single-user / low-concurrency "
                    "deployments."
                ),
                id="schedules.W001",
            )
        )
    return errors
