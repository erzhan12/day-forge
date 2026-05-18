from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from inertia import render as inertia_render

from templates_mgr.models import Rule, Template
from templates_mgr.preferences import get_user_preferences


@ensure_csrf_cookie
@login_required
def settings_view(request):
    """Inertia render for ``/settings/``.

    Server-side fetch of the user's templates and rules so the page boots
    without a second JSON round-trip. ``request.user`` filtering is the
    only multi-tenant gate — there is no pagination because both lists
    are bounded (≤2 templates and ≤MAX_RULES_PER_USER rules per user).
    """
    templates = list(
        Template.objects.filter(user=request.user).order_by("type")
    )
    rules = list(
        Rule.objects.filter(user=request.user).order_by("-priority", "id")
    )
    # Resolve preferences exactly once per render so the SSR data-theme
    # and the Inertia ``ui_preferences`` prop always agree.
    prefs = get_user_preferences(request.user)

    return inertia_render(
        request,
        "Settings",
        {
            "templates": [
                {
                    "id": t.id,
                    "name": t.name,
                    "type": t.type,
                    "blocks": list(t.blocks),
                }
                for t in templates
            ],
            "rules": [
                {
                    "id": r.id,
                    "text": r.text,
                    "is_active": r.is_active,
                    "priority": r.priority,
                }
                for r in rules
            ],
            "ui_preferences": {"theme": prefs.theme},
        },
        template_data={"initial_theme": prefs.theme},
    )
