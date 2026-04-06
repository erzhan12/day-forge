import django
from django.conf import settings

# Ensure Django is set up before tests run
if not settings.configured:
    django.setup()
