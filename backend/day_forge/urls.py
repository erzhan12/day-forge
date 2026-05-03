from ai import views as ai_views
from django.contrib import admin
from django.urls import path
from schedules import api as schedules_api
from schedules import views as schedules_views
from templates_mgr import api as templates_api
from templates_mgr import views as templates_views

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
]
