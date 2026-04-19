from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ai'

    def ready(self):
        # Register system checks (LocMemCache-with-AI-in-prod guard).
        from . import checks  # noqa: F401
