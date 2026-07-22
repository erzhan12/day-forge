from django.apps import AppConfig


class HabiticaSyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "habitica_sync"

    def ready(self):
        from . import checks  # noqa: F401
