import datetime
import json

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from inertia import render as inertia_render
from templates_mgr.models import Template

from schedules.models import Schedule, TimeBlock


def root_redirect(request):
    today = datetime.date.today().isoformat()
    return redirect("schedule", date=today)


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("root")

    if request.method == "GET":
        return inertia_render(request, "Login", {"errors": {}})

    # Inertia may send JSON or form data
    if request.content_type == "application/json":
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return inertia_render(
                request, "Login", {"errors": {"non_field": "Invalid request body."}}
            )
        username = body.get("username", "")
        password = body.get("password", "")
    else:
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
    user = authenticate(request, username=username, password=password)
    if user is not None:
        login(request, user)
        today = datetime.date.today().isoformat()
        return redirect("schedule", date=today)
    return inertia_render(
        request, "Login", {"errors": {"non_field": "Invalid credentials"}}
    )


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

    schedule, created = Schedule.objects.get_or_create(
        user=request.user, date=parsed_date
    )
    blocks = TimeBlock.objects.filter(schedule=schedule).order_by(
        "start_time", "sort_order"
    )

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

    # Saturday=5, Sunday=6 are weekends.
    slot_type = (
        Template.Type.WEEKEND
        if parsed_date.weekday() >= 5
        else Template.Type.WEEKDAY
    )
    template_exists = Template.objects.filter(
        user=request.user, type=slot_type
    ).exists()
    api_key_set = bool(settings.LLM_API_KEY and settings.LLM_API_KEY.strip())

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
        },
    )
