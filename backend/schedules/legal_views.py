"""Public legal pages: ``/privacy/`` and ``/terms/`` (feature 0078).

Kept out of ``schedules/views.py`` because these views share nothing with
schedule rendering — no models, no Inertia, and, unlike every other page
view in this project, no authentication. Same narrow-module convention as
``schedules/category_api.py`` and ``calendar_sync/travel_rules.py``.
"""

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

# Revision date shown on both legal pages. Format: "D Month YYYY".
# Bump it in the same commit that changes the wording of either template —
# nothing derives it from git, so a stale date here is the only failure mode.
LEGAL_LAST_UPDATED = "7 September 2026"


def _render_legal(request, template_name):
    """Render a public legal page.

    Deliberately **not** ``@login_required``: the Google OAuth consent
    screen for this deployment links to ``/privacy/`` and ``/terms/``, and
    Google's reviewers (plus any user reading the consent screen before
    they have an account) must reach them anonymously. Every page view in
    ``schedules.views`` is login-gated; these two are the exception, so the
    absence of the decorator is intentional rather than an oversight.

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
