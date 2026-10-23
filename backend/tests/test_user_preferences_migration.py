import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.mark.django_db(transaction=True)
def test_gap_migration_preserves_existing_preferences():
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    old = [("templates_mgr", "0005_userpreferences_chat_suggestions")]
    try:
        executor.migrate(old)
        apps = executor.loader.project_state(old).apps
        user = apps.get_model("auth", "User").objects.create(username="gap-migration")
        row = apps.get_model("templates_mgr", "UserPreferences").objects.create(
            user_id=user.pk, theme="strategic", chat_suggestions=["Keep"],
        )
        target = [("templates_mgr", "0006_userpreferences_default_block_gap_minutes")]
        executor = MigrationExecutor(connection)
        executor.migrate(target)
        upgraded = executor.loader.project_state(target).apps.get_model(
            "templates_mgr", "UserPreferences",
        ).objects.get(pk=row.pk)
        assert (upgraded.user_id, upgraded.theme, upgraded.chat_suggestions,
                upgraded.default_block_gap_minutes) == (user.pk, "strategic", ["Keep"], 10)
    finally:
        MigrationExecutor(connection).migrate(leaves)
