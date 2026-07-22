from ai import views as ai_views
from analytics import views as analytics_views
from calendar_sync import travel_rules as calendar_travel_rules
from calendar_sync import views as calendar_views
from django.contrib import admin
from django.urls import path
from gcal_sync import views as gcal_views
from habitica_sync import views as habitica_views
from schedules import api as schedules_api
from schedules import views as schedules_views
from templates_mgr import api as templates_api
from templates_mgr import views as templates_views
from todoist_sync import views as todoist_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Auth
    path("accounts/login/", schedules_views.login_view, name="login"),
    path("accounts/logout/", schedules_views.logout_view, name="logout"),
    # Pages
    path("", schedules_views.root_redirect, name="root"),
    path("schedule/<str:date>/", schedules_views.schedule_view, name="schedule"),
    path("settings/", templates_views.settings_view, name="settings"),
    # API: schedules + blocks
    path(
        "api/schedules/<str:date>/blocks/",
        schedules_api.create_block,
        name="create_block",
    ),
    path("api/blocks/<int:pk>/", schedules_api.block_detail, name="block_detail"),
    path("api/blocks/reorder/", schedules_api.reorder_blocks, name="reorder_blocks"),
    path(
        "api/schedules/<str:date>/blocks/restore/",
        schedules_api.restore_blocks,
        name="restore_blocks",
    ),
    # From-event create (feature 0026): the single sanctioned off-grid
    # create path. The ``/from-event/`` literal disambiguates from the
    # plain ``blocks/`` route above.
    path(
        "api/schedules/<str:date>/blocks/from-event/",
        schedules_api.create_block_from_event,
        name="create_block_from_event",
    ),
    # API: templates + rules
    path(
        "api/templates/",
        templates_api.templates_collection,
        name="templates_collection",
    ),
    path(
        "api/templates/<int:pk>/",
        templates_api.template_detail,
        name="template_detail",
    ),
    path(
        "api/rules/",
        templates_api.rules_collection,
        name="rules_collection",
    ),
    path(
        "api/rules/<int:pk>/",
        templates_api.rule_detail,
        name="rule_detail",
    ),
    # Per-user UI preferences (theme, future settings). Distinct from
    # templates_mgr.Template (schedule templates) despite the shared app.
    path(
        "api/user/preferences/",
        templates_api.user_preferences,
        name="user_preferences",
    ),
    # API: AI
    path(
        "api/ai/schedules/<str:date>/command/",
        ai_views.ai_command,
        name="ai_command",
    ),
    path(
        "api/ai/schedules/<str:date>/generate-draft/",
        ai_views.ai_generate_draft,
        name="ai_generate_draft",
    ),
    path(
        "api/ai/schedules/<str:date>/chat/",
        ai_views.ai_chat,
        name="ai_chat",
    ),
    # API: CalDAV / Apple Calendar (feature 0011)
    path(
        "api/calendar/account/",
        calendar_views.account,
        name="caldav_account",
    ),
    path(
        "api/calendar/events/<str:date>/",
        calendar_views.events,
        name="caldav_events",
    ),
    # Travel-time rules for from-event adds (feature 0026) — provider-
    # agnostic, hence under /api/calendar/ but owned by calendar_sync.
    path(
        "api/calendar/travel-rules/",
        calendar_travel_rules.travel_rules_collection,
        name="travel_rules_collection",
    ),
    path(
        "api/calendar/travel-rules/<int:pk>/",
        calendar_travel_rules.travel_rule_detail,
        name="travel_rule_detail",
    ),
    # API: Google Calendar (feature 0022)
    path(
        "api/calendar/google/connect/",
        gcal_views.connect,
        name="gcal_connect",
    ),
    path(
        "api/calendar/google/callback/",
        gcal_views.callback,
        name="gcal_callback",
    ),
    path(
        "api/calendar/google/accounts/",
        gcal_views.accounts,
        name="gcal_accounts",
    ),
    path(
        "api/calendar/google/accounts/<int:account_id>/",
        gcal_views.account_detail,
        name="gcal_account_detail",
    ),
    path(
        "api/calendar/google/events/<str:date>/",
        gcal_views.events,
        name="gcal_events",
    ),
    # API: Todoist (feature 0020)
    path(
        "api/todoist/account/",
        todoist_views.account,
        name="todoist_account",
    ),
    path(
        "api/todoist/tasks/<str:date>/",
        todoist_views.tasks,
        name="todoist_tasks",
    ),
    # The trailing ``/complete/`` literal disambiguates this from the
    # ``<str:date>/`` route above (which has no trailing segment), so no
    # path collision despite both leading with ``<str:...>``.
    path(
        "api/todoist/tasks/<str:task_id>/complete/",
        todoist_views.complete,
        name="todoist_complete",
    ),
    # API: Habitica (feature 0024)
    path(
        "api/habitica/account/",
        habitica_views.account,
        name="habitica_account",
    ),
    path(
        "api/habitica/tasks/<str:date>/",
        habitica_views.tasks,
        name="habitica_tasks",
    ),
    path(
        "api/habitica/tasks/<str:task_id>/complete/",
        habitica_views.complete,
        name="habitica_complete",
    ),
    # Analytics
    path(
        "analytics/<str:date>/",
        analytics_views.analytics_view,
        name="analytics",
    ),
    path(
        "api/analytics/schedules/<str:date>/mark-reviewed/",
        analytics_views.mark_reviewed,
        name="mark_reviewed",
    ),
    path(
        "api/analytics/reviews/<int:pk>/notes/",
        analytics_views.update_review_notes,
        name="update_review_notes",
    ),
]
