from django.contrib import admin
from django.urls import path
from schedules import api as schedules_api
from schedules import views as schedules_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # Auth
    path("accounts/login/", schedules_views.login_view, name="login"),
    path("accounts/logout/", schedules_views.logout_view, name="logout"),
    # Pages
    path("", schedules_views.root_redirect, name="root"),
    path("schedule/<str:date>/", schedules_views.schedule_view, name="schedule"),
    # API
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
]
