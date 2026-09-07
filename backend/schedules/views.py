import datetime
import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from inertia import render as inertia_render
from templates_mgr.models import Template
from templates_mgr.preferences import (
    get_user_preferences,
    ui_preferences_payload,
)

from schedules.categories import ordered_categories, serialize_category
from schedules.models import Schedule, TimeBlock
from schedules.window import get_schedule_settings, user_local_date

# Login renders Strategic statically — no user preference exists pre-auth.
# Centralized so every login render path gets the same template_data; a
# missed call would silently fall back to ``'classic'`` via base.html.
_LOGIN_TEMPLATE_DATA = {"initial_theme": "strategic"}


def _render_login(request, props: dict):
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


# Revision date shown on both legal pages. Bump it in the same commit that
# changes the wording of either template — nothing derives it from git, so a
# stale date here is the only failure mode.
LEGAL_LAST_UPDATED = "7 September 2026"


def _render_legal(request, template_name):
    """Render a public legal page.

    Deliberately **not** ``@login_required``: the Google OAuth consent
    screen for this deployment links to ``/privacy/`` and ``/terms/``, and
    Google's reviewers (plus any user reading the consent screen before
    they have an account) must reach them anonymously. Every other page
    view in this module is login-gated; these two are the exception, so
    the absence of the decorator is intentional rather than an oversight.

    Plain ``django.shortcuts.render`` rather than ``inertia_render``: the
    content is static, needs no props, and must survive a deploy where the
    Vue bundle has not been rebuilt.
    """
    return render(
        request,
        template_name,
        {
            "last_updated": LEGAL_LAST_UPDATED,
            "contact_email": settings.LEGAL_CONTACT_EMAIL,
        },
    )


# HEAD is allowed alongside GET because crawlers and link checkers (Google's
# among them) probe these URLs with HEAD; Django does not fold HEAD into GET.
@require_http_methods(["GET", "HEAD"])
def privacy_view(request):
    return _render_legal(request, "legal/privacy.html")


@require_http_methods(["GET", "HEAD"])
def terms_view(request):
    return _render_legal(request, "legal/terms.html")


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("root")

    if request.method == "GET":
        return _render_login(request, {"errors": {}})

    # Inertia may send JSON or form data
    if request.content_type == "application/json":
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return _render_login(request, {"errors": {"non_field": "Invalid request body."}})
        username = body.get("username", "")
        password = body.get("password", "")
    else:
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
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


@ensure_csrf_cookie
@login_required
def schedule_view(request, date):
    try:
        parsed_date = datetime.date.fromisoformat(date)
    except ValueError:
        return HttpResponseBadRequest("Invalid date format. Use YYYY-MM-DD.")

    schedule, created = Schedule.objects.get_or_create(user=request.user, date=parsed_date)
    blocks = TimeBlock.objects.filter(schedule=schedule).order_by("start_time", "sort_order")

    blocks_data = [
        {
            "id": b.id,
            "title": b.title,
            "start_time": b.start_time.strftime("%H:%M"),
            "end_time": b.end_time.strftime("%H:%M"),
            "category": b.category,
            "is_completed": b.is_completed,
            "sort_order": b.sort_order,
        }
        for b in blocks
    ]

    slot_type = Template.slot_type_for_date(parsed_date)
    template_exists = Template.objects.filter(user=request.user, type=slot_type).exists()
    api_key_set = bool(settings.LLM_API_KEY and settings.LLM_API_KEY.strip())
    prefs = get_user_preferences(request.user)
    schedule_settings = get_schedule_settings(request.user)
    categories = ordered_categories(request.user)

    return inertia_render(
        request,
        "Schedule",
        {
            "schedule": {
                "id": schedule.id,
                "date": str(schedule.date),
                "status": schedule.status,
            },
            "blocks": blocks_data,
            "categories": [serialize_category(category) for category in categories],
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
            "ui_preferences": ui_preferences_payload(prefs),
            "schedule_window": {
                "start": schedule_settings.window.start_str,
                "end": schedule_settings.window.end_str,
                "time_zone": schedule_settings.time_zone,
            },
        },
        template_data={"initial_theme": prefs.theme},
    )
