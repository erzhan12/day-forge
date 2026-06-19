from django.apps import AppConfig


class TodoistSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "todoist_sync"

    def ready(self):
        from . import checks  # noqa: F401
