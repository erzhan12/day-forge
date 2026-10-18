"""Production-assets release rehearsal on an isolated /tmp database, port 8008.

Usage: uv run python backend/scripts/release_browser_server.py ROOT BUILD_DIR
Restart with another BUILD_DIR to rehearse an upgrade or rollback. Never uses the
working database or changes .env. Provider calls use the configured local key.
"""

import datetime as dt
import json
import os
import sys
from pathlib import Path

if len(sys.argv) != 3:
    raise SystemExit("Expected /tmp/ROOT and BUILD_DIR")
root, build = [Path(arg).resolve() for arg in sys.argv[1:]]
if not root.is_relative_to(Path("/tmp").resolve()) or not build.is_relative_to(root):
    raise SystemExit("Use a build inside an isolated /tmp directory")
root.mkdir(parents=True, exist_ok=True)
marker = root / "release-fixture.marker"
if (root / "fixture.sqlite3").exists() and not marker.exists():
    raise SystemExit("Refusing an existing unmarked database")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(
    {
        "DJANGO_SETTINGS_MODULE": "day_forge.settings",
        "DEBUG": "0",
        "FRONTEND_BUILD_DIR": str(build),
        "DJANGO_SECRET_KEY": "isolated-release-rehearsal-not-for-production",
        "ALLOWED_HOSTS": "127.0.0.1,localhost",
    }
)

import django  # noqa: E402
from django.conf import settings  # noqa: E402

settings.DATABASES["default"]["NAME"] = root / "fixture.sqlite3"
settings.STATIC_ROOT = root / "staticfiles"
settings.SECURE_SSL_REDIRECT = False
settings.SECURE_HSTS_SECONDS = 0
settings.SESSION_COOKIE_SECURE = False
settings.CSRF_COOKIE_SECURE = False
settings.SESSION_COOKIE_NAME = "release_fixture_session"
settings.CSRF_TRUSTED_ORIGINS = ["http://localhost:8008", "http://127.0.0.1:8008"]
settings.CACHES["default"]["KEY_PREFIX"] = root.name

# Record release boundaries without cookies, credentials or prompt contents.
import types  # noqa: E402

hooks = types.ModuleType("scripts.release_browser_hooks")
sys.modules[hooks.__name__] = hooks


class ReleaseAudit:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        with (root / "requests.jsonl").open("a") as file:
            file.write(
                json.dumps(
                    {
                        "release": settings.INERTIA_VERSION,
                        "method": request.method,
                        "path": request.path,
                        "frontend": request.headers.get("X-Frontend-Version"),
                        "inertia": request.headers.get("X-Inertia-Version"),
                        "status": response.status_code,
                        "location": response.get("X-Inertia-Location"),
                    }
                )
                + "\n"
            )
        return response


hooks.ReleaseAudit = ReleaseAudit
settings.MIDDLEWARE.insert(0, "scripts.release_browser_hooks.ReleaseAudit")
django.setup()

from django.contrib.auth.models import User  # noqa: E402
from django.core.management import call_command  # noqa: E402
from schedules.models import Schedule, TimeBlock  # noqa: E402

call_command("migrate", verbosity=0)
call_command("collectstatic", verbosity=0, interactive=False)
if not marker.exists():
    user = User.objects.create_user(
        username="release-browser", password="release-browser-local-only"
    )
    call_command("seed_templates", user=user.username, verbosity=0)
    for day in [dt.date.today(), dt.date(2027, 7, 11)]:
        schedule = Schedule.objects.create(user=user, date=day, status="active")
        TimeBlock.objects.create(
            schedule=schedule,
            title="Baseline block",
            start_time="09:00",
            end_time="10:00",
            category="work",
            sort_order=0,
        )
    marker.touch()
print(f"Release {settings.INERTIA_VERSION}; isolated database: {root}", flush=True)
call_command("runserver", "127.0.0.1:8008", use_reloader=False)
