import datetime
import uuid

from calendar_sync.models import CalDAVAccount, TravelRule
from calendar_sync.travel_rules import serialize_travel_rule
from common.http import parse_json_object
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.db import OperationalError, connection, transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from gcal_sync.models import GoogleCalendarAccount
from habitica_sync.models import HabiticaAccount
from inertia import render as inertia_render
from inertia.http import clear_history
from templates_mgr.models import Template, UserPreferences
from templates_mgr.preferences import (
    UserPreferencesDTO,
    get_user_preferences,
    normalize_chat_suggestions,
    normalize_theme,
    ui_preferences_payload,
)
from todoist_sync.models import TodoistAccount

from schedules.categories import ordered_categories, serialize_category
from schedules.models import Category, Schedule, UserScheduleSettings
from schedules.mutations import ScheduleChanged, run_user_maintenance
from schedules.serialization import serialize_block, serialize_schedule
from schedules.window import (
    ScheduleSettings,
    ScheduleWindow,
    get_schedule_settings,
    user_local_date,
)

# Login renders Strategic statically — no user preference exists pre-auth.
# Centralized so every login render path gets the same template_data; a
# missed call would silently fall back to ``'classic'`` via base.html.
_LOGIN_TEMPLATE_DATA = {"initial_theme": "strategic"}


def _render_login(request, props: dict):
    # Covers logout redirects and expired sessions. The Inertia client discards
    # its history key before rendering Login, invalidating earlier private pages.
    clear_history(request)
    return inertia_render(request, "Login", props, template_data=_LOGIN_TEMPLATE_DATA)


def root_redirect(request):
    # `root_redirect` is undecorated, so anonymous requests reach it. Only
    # authenticated users have persisted settings; unauthenticated `/` stays
    # on the host clock (as before feature 0077) — resolving user-local for
    # AnonymousUser would hit `get_or_create(user=AnonymousUser)` → TypeError.
    if request.user.is_authenticated:
        today = user_local_date(request.user).isoformat()
    else:
        today = datetime.date.today().isoformat()
    return redirect("schedule", date=today)


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("root")

    if request.method == "GET":
        return _render_login(request, {"errors": {}})

    # Inertia may send JSON or form data
    if request.content_type == "application/json":
        body, error = parse_json_object(request, max_bytes=None)
        if error is not None:
            return _render_login(request, {"errors": {"non_field": "Invalid request body."}})
        username = body.get("username", "")
        password = body.get("password", "")
    else:
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        return _render_login(request, {"errors": {"non_field": "Invalid request body."}})
    user = authenticate(request, username=username, password=password)
    if user is not None:
        login(request, user)
        today = user_local_date(user).isoformat()
        return redirect("schedule", date=today)
    return _render_login(request, {"errors": {"non_field": "Invalid credentials"}})


@require_http_methods(["POST"])
@login_required
def logout_view(request):
    logout(request)
    return redirect("login")


def _integration_bootstrap(user, date: datetime.date, time_zone: str) -> dict:
    """A user-scoped snapshot for the Schedule page's initial external state."""
    return {
        "snapshot_id": uuid.uuid4().hex,
        "user_id": user.pk,
        "date": date.isoformat(),
        "time_zone": time_zone,
        "connected": {
            "apple": CalDAVAccount.objects.filter(user=user).exists(),
            "google": GoogleCalendarAccount.objects.filter(user=user).exists(),
            "todoist": TodoistAccount.objects.filter(user=user).exists(),
            "habitica": HabiticaAccount.objects.filter(user=user).exists(),
        },
        "travel_rules": [
            serialize_travel_rule(rule)
            for rule in TravelRule.objects.filter(user=user).order_by("order", "id")
        ],
    }


def _read_schedule_page(user, date, slot_type):
    """Capture day and page policies from one read snapshot without reserving a writer."""
    with transaction.atomic():
        # On PostgreSQL this serializes the read with shared-lock writers.
        # SQLite ignores select_for_update but keeps a read snapshot.
        get_user_model().objects.select_for_update().get(pk=user.pk)
        schedule = Schedule.objects.filter(user=user, date=date).first()
        settings_row = UserScheduleSettings.objects.filter(user=user).first()
        prefs_row = UserPreferences.objects.filter(user=user).first()
        categories = list(Category.objects.filter(user=user).order_by("sort_order", "id"))
        if schedule is None or settings_row is None or prefs_row is None or not categories:
            return None
        blocks = list(schedule.time_blocks.order_by("start_time", "sort_order", "id"))
        template_exists = Template.objects.filter(user=user, type=slot_type).exists()
        return {
            "schedule": serialize_schedule(schedule),
            "blocks": [serialize_block(block) for block in blocks],
            "categories": [serialize_category(category) for category in categories],
            "settings": ScheduleSettings(
                ScheduleWindow(settings_row.day_start, settings_row.day_end),
                settings_row.time_zone,
            ),
            "preferences": UserPreferencesDTO(
                theme=normalize_theme(prefs_row.theme),
                chat_suggestions=tuple(normalize_chat_suggestions(prefs_row.chat_suggestions)),
            ),
            "template_exists": template_exists,
        }


def _create_schedule_page_rows(user_id, date, slot_type):
    """Create first-use rows under the same lock as schedule and policy writes."""
    def create_rows(user):
        schedule, created = Schedule.objects.get_or_create(user=user, date=date)
        get_schedule_settings(user)
        get_user_preferences(user)
        ordered_categories(user)
        return created, _read_schedule_page(user, date, slot_type)

    return run_user_maintenance(user_id, create_rows)


def _schedule_unavailable_response():
    response = HttpResponse("Schedule temporarily unavailable. Please try again.", status=503)
    response["Retry-After"] = "1"
    return response


@ensure_csrf_cookie
@login_required
def schedule_view(request, date):
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return HttpResponseBadRequest("Invalid date format. Use YYYY-MM-DD.")

    slot_type = Template.slot_type_for_date(parsed_date)
    try:
        page = _read_schedule_page(request.user, parsed_date, slot_type)
        created = False
        if page is None:
            created, page = _create_schedule_page_rows(request.user.pk, parsed_date, slot_type)
    except ScheduleChanged:
        return _schedule_unavailable_response()
    except OperationalError as exc:
        if connection.vendor != "sqlite" or not any(
            marker in str(exc).lower() for marker in ("locked", "busy")
        ):
            raise
        return _schedule_unavailable_response()

    if page is None:
        return _schedule_unavailable_response()
    schedule_settings = page["settings"]
    prefs = page["preferences"]
    template_exists = page["template_exists"]
    api_key_set = bool(settings.LLM_API_KEY and settings.LLM_API_KEY.strip())

    return inertia_render(
        request,
        "Schedule",
        {
            "schedule": page["schedule"],
            "blocks": page["blocks"],
            "categories": page["categories"],
            "date": str(parsed_date),
            # One-shot signal: the auto-draft trigger only fires on the
            # request that *created* the Schedule row. The frontend
            # tracks attempted dates per-component-instance to prevent
            # refire (see Schedule.vue's attemptedAutoDraftDates set).
            #
            # Including the template-existence check up front avoids
            # burning the 10/hr draft budget on a guaranteed 422.
            "auto_draft_pending": created and template_exists and api_key_set,
            # Ongoing capability flag, exposed separately so
            # RegenerateDraftButton stays accurate beyond the first
            # render. ``auto_draft_pending`` flips false after the first
            # paint, so it can't double as a capability signal.
            "has_template_for_type": template_exists,
            "slot_type": slot_type,
            # Seconds between background external-task refreshes while the
            # left task rail is open; ``0`` disables polling.
            "external_tasks_poll_interval": (settings.EXTERNAL_TASKS_POLL_INTERVAL_SECONDS),
            # Inertia resolves callable props after filtering partial reloads.
            # Date-only visits therefore avoid the account/rule queries while
            # full visits (including the return from Settings) get a new snapshot.
            "integration_bootstrap": lambda: _integration_bootstrap(
                request.user, parsed_date, schedule_settings.time_zone
            ),
            "ui_preferences": ui_preferences_payload(prefs),
            "schedule_window": {
                "start": schedule_settings.window.start_str,
                "end": schedule_settings.window.end_str,
                "time_zone": schedule_settings.time_zone,
            },
        },
        template_data={"initial_theme": prefs.theme},
    )
