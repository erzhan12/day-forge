from django.apps import AppConfig


class WhoopSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "whoop_sync"

    def ready(self):
        from . import checks  # noqa: F401
