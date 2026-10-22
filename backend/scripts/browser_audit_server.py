"""Isolated A00–A07 browser fixture server. Never imported by the application.

Run with ``uv run python backend/scripts/browser_audit_server.py /tmp/NEW_DIR``.
Uses a fresh SQLite database, a namespaced cache, synthetic accounts, and provider
stubs. Only listens on 127.0.0.1:8007. See the browser audit report for controls.

``--draft-window`` uses production frontend assets (run ``make frontend-build``
first), local Redis, a dummy AI key and empty 2027-08-02 through 2027-08-06 draft
days at revision 7. Set ``draft_actions`` in controls.json to the desired provider
actions. The real SDK transport is replaced; no external AI request is made.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("root", type=Path)
parser.add_argument("--draft-window", action="store_true", help="Seed empty draft test days")
args = parser.parse_args()
ROOT = args.root.resolve()
if ROOT.exists() or not ROOT.is_relative_to(Path("/tmp").resolve()):
    raise SystemExit("Pass a NEW directory under /tmp (existing data is never replaced)")
ROOT.mkdir(mode=0o700)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "day_forge.settings")
if args.draft_window:
    os.environ.update(
        DEBUG="0",
        DJANGO_SECRET_KEY="isolated-draft-window-fixture-not-for-production",
        ALLOWED_HOSTS="127.0.0.1,localhost",
        LLM_API_KEY="local-fixture-only",
        REDIS_URL="redis://127.0.0.1:6379/0",
    )

from django.conf import settings  # noqa: E402

settings.DATABASES["default"]["NAME"] = ROOT / "fixture.sqlite3"
settings.CACHES["default"]["KEY_PREFIX"] = ROOT.name
settings.SESSION_COOKIE_NAME = "audit_sessionid"
settings.CSRF_COOKIE_NAME = "XSRF-TOKEN"  # Frontend's existing header contract.
settings.MIDDLEWARE.append("scripts.browser_audit_hooks.FaultControls")
if args.draft_window:
    settings.STATIC_ROOT = ROOT / "staticfiles"
    settings.SECURE_SSL_REDIRECT = False
    settings.SECURE_HSTS_SECONDS = 0
    settings.SESSION_COOKIE_SECURE = False
    settings.CSRF_COOKIE_SECURE = False
    settings.LLM_DRAFT_RATE_LIMIT_PER_HOUR = 100

# Register a separate in-memory module so Django can import the middleware.
import types  # noqa: E402

hooks = types.ModuleType("scripts.browser_audit_hooks")
sys.modules[hooks.__name__] = hooks


def controls():
    return json.loads((ROOT / "controls.json").read_text())


def record(kind, **data):
    with (ROOT / "audit.jsonl").open("a") as file:
        file.write(json.dumps({"kind": kind, **data}, default=str) + "\n")


class FaultControls:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.http import JsonResponse

        config = controls()
        if request.method == "PATCH" and request.path.startswith("/api/user/categories/"):
            status = config.get("category_error", 0)
            if status:
                record("category_rejected", status=status, body=request.body.decode())
                return JsonResponse(
                    {"errors": {"detail": f"Controlled category {status}"}}, status=status
                )
        if (
            config.get("delay_write")
            and request.method == "POST"
            and request.path == "/api/schedules/2027-05-10/blocks/"
        ):
            config["delay_write"] = False
            (ROOT / "controls.json").write_text(json.dumps(config))
            (ROOT / "write_waiting").touch()
            deadline = time.monotonic() + 90
            while not (ROOT / "release_write").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            record("write_released", explicitly_released=(ROOT / "release_write").exists())
        response = self.get_response(request)
        if request.path.startswith("/api/"):
            record(
                "http",
                path=request.path,
                method=request.method,
                status=response.status_code,
                response=response.content.decode() if not response.streaming else "streaming",
            )
        return response


hooks.FaultControls = FaultControls
(ROOT / "controls.json").write_text(json.dumps({"google": "good", "ai": "good"}))

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402

call_command("migrate", verbosity=0)

from ai import service as ai_service  # noqa: E402
from analytics.services import freeze_review_snapshot  # noqa: E402
from calendar_sync.models import TravelRule  # noqa: E402
from calendar_sync.schemas import NormalizedEvent  # noqa: E402
from django.contrib.auth.models import User  # noqa: E402
from gcal_sync import cache as google_cache  # noqa: E402
from gcal_sync import service as google_service  # noqa: E402
from gcal_sync.models import GoogleCalendarAccount  # noqa: E402
from schedules.categories import ordered_categories  # noqa: E402
from schedules.models import Schedule, TimeBlock, UserScheduleSettings  # noqa: E402

user = User.objects.create_user("audit-browser-local", password="audit-browser-local-only")
UserScheduleSettings.objects.create(user=user, time_zone="UTC")
ordered_categories(user)
if args.draft_window:
    from templates_mgr.models import Template

    UserScheduleSettings.objects.filter(user=user).update(
        day_start=dt.time(5, 0), day_end=dt.time(22, 0)
    )
    for slot_type in ("weekday", "weekend"):
        Template.objects.create(
            user=user,
            name=f"Draft window {slot_type}",
            type=slot_type,
            blocks=[
                {
                    "title": "Valid fixture block",
                    "start_time": "09:00",
                    "end_time": "09:30",
                    "category": "work",
                }
            ],
        )
    for day in range(2, 7):
        Schedule.objects.create(user=user, date=dt.date(2027, 8, day), revision=7)
    call_command("collectstatic", verbosity=0, interactive=False)
for day in (
    dt.date.today(),
    dt.date(2027, 5, 10),
    dt.date(2027, 5, 11),
    dt.date(2027, 5, 12),
    dt.date(2027, 5, 13),
    dt.date(2026, 10, 14),
    dt.date(2026, 10, 15),
):
    schedule = Schedule.objects.create(user=user, date=day, status="active")
    if day in (dt.date(2026, 10, 14), dt.date(2026, 10, 15)):
        TimeBlock.objects.create(
            schedule=schedule,
            title=f"Reviewed {day.day}",
            start_time="09:00",
            end_time="09:30",
            category="work",
            is_completed=True,
        )
        schedule.status = "reviewed"
        schedule.save()
        review = freeze_review_snapshot(schedule, revision=0)
        review.notes = "Retain audit note"
        review.save()
        if day.day == 15:
            Schedule.objects.filter(pk=schedule.pk).update(revision=1)
for index in (1, 2):
    GoogleCalendarAccount.objects.create(
        user=user,
        google_account_id=f"fake-{index}",
        email=f"fixture{index}@example.invalid",
        refresh_token_encrypted=b"NOT_A_REAL_TOKEN",
    )
TravelRule.objects.create(
    user=user,
    keyword="Airport",
    travel_there_minutes=20,
    travel_back_minutes=10,
    category="personal",
)


async def fetch_events(account, date, time_zone):
    mode = controls()["google"]
    if mode == "provider_error" or (mode == "partial" and account.google_account_id == "fake-2"):
        raise google_service.GoogleCalProviderError("Controlled provider failure")
    if mode == "credentials_error":
        raise google_service.GoogleCalAuthError("Controlled credentials failure")
    if mode == "empty" or account.google_account_id == "fake-2":
        return []

    def event(title, start, end, uid):
        return NormalizedEvent(
            title,
            dt.datetime.combine(date, dt.time.fromisoformat(start), dt.UTC),
            dt.datetime.combine(date, dt.time.fromisoformat(end), dt.UTC),
            "Audit calendar",
            False,
            uid,
            account.email,
        )

    return [
        event("Private fixture appointment", "10:03", "10:37", "audit-plain"),
        event("Airport fixture", "15:00", "16:00", "audit-travel"),
    ]


async def no_cached_events(*args):
    return None


async def completion(**kwargs):
    config = controls()
    mode = config["ai"]
    record("sdk", mode=mode, messages=kwargs["messages"])
    actions = config.get("draft_actions", [])
    if mode in ("invalid", "add"):
        actions = [
            {
                "type": "add",
                "title": "Audit AI recovery",
                "start_time": "13:00",
                "end_time": "13:30",
                "category": "work",
            }
        ]
    content = {
        "actions": actions,
        "explanation": "" if mode == "invalid" else "Audit response accepted.",
        "ask": None,
    }
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))]
    )


google_service.fetch_events_for_account = fetch_events
google_cache.get_cached_events = no_cached_events
ai_service._get_client = lambda: SimpleNamespace(
    chat=SimpleNamespace(completions=SimpleNamespace(create=completion))
)
print(f"Fixture server ready: http://localhost:8007; evidence: {ROOT}", flush=True)
call_command("runserver", "127.0.0.1:8007", use_reloader=False)
