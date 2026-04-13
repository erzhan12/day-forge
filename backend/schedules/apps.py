from django.apps import AppConfig


class SchedulesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'schedules'

    def ready(self):
        # Register system checks (e.g. SQLite-in-production warning).
        from . import checks  # noqa: F401
