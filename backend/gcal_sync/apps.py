from django.apps import AppConfig


class GcalSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gcal_sync"

    def ready(self):
        from . import checks  # noqa: F401
