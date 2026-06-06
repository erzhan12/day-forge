#!/usr/bin/env sh
set -e

echo "[entrypoint] applying migrations"
python manage.py migrate --noinput

echo "[entrypoint] collecting static files"
python manage.py collectstatic --noinput

# Idempotent superuser creation from DJANGO_SUPERUSER_* (skipped if unset).
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "[entrypoint] ensuring superuser '$DJANGO_SUPERUSER_USERNAME' exists"
    python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ["DJANGO_SUPERUSER_USERNAME"]
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"[entrypoint] created superuser {username}")
else:
    print(f"[entrypoint] superuser {username} already exists; leaving as-is")
PY
fi

echo "[entrypoint] starting: $*"
exec "$@"
