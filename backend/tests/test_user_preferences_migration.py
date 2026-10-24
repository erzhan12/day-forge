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


@pytest.mark.django_db(transaction=True)
def test_gap_upgrade_supports_legacy_preferences_insert_and_preserves_custom_values():
    """An image rollback still creates preferences through the pre-gap ORM."""
    executor = MigrationExecutor(connection)
    leaves = executor.loader.graph.leaf_nodes()
    gap_migration = [("templates_mgr", "0006_userpreferences_default_block_gap_minutes")]
    try:
        executor.migrate(gap_migration)
        apps = executor.loader.project_state(gap_migration).apps
        user_model = apps.get_model("auth", "User")
        preferences_model = apps.get_model("templates_mgr", "UserPreferences")
        ids = []
        for gap in (0, 10, 20):
            user = user_model.objects.create(username=f"gap-retained-{gap}")
            row = preferences_model.objects.create(
                user_id=user.pk, theme="strategic", chat_suggestions=["Keep"],
                default_block_gap_minutes=gap,
            )
            ids.append(row.pk)
        before = list(preferences_model.objects.filter(pk__in=ids).order_by("pk").values())
        legacy_preferences = executor.loader.project_state([
            ("templates_mgr", "0005_userpreferences_chat_suggestions"),
        ]).apps.get_model("templates_mgr", "UserPreferences")

        MigrationExecutor(connection).migrate(leaves)
        current = MigrationExecutor(connection).loader.project_state(leaves).apps
        current_preferences = current.get_model("templates_mgr", "UserPreferences")
        after = list(current_preferences.objects.filter(pk__in=ids).order_by("pk").values())
        assert after == before

        new_user = current.get_model("auth", "User").objects.create(username="gap-legacy-insert")
        legacy_row = legacy_preferences.objects.create(
            user_id=new_user.pk, theme="light_premium", chat_suggestions=["From old image"],
        )
        saved = current_preferences.objects.get(pk=legacy_row.pk)
        assert (saved.default_block_gap_minutes, saved.theme, saved.chat_suggestions) == (
            10, "light_premium", ["From old image"],
        )
    finally:
        MigrationExecutor(connection).migrate(leaves)
