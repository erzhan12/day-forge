import datetime

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from inertia import render as inertia_render

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

    schedule, _ = Schedule.objects.get_or_create(user=request.user, date=parsed_date)
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
        },
    )
