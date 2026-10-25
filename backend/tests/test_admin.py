import datetime

import pytest
from ai.admin import AIInteractionAdmin
from ai.models import AIInteraction
from analytics.admin import DailyReviewAdmin
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from django.urls import reverse
from schedules.admin import ScheduleAdmin, TimeBlockAdmin, UserScheduleSettingsAdmin
from schedules.models import Schedule, TimeBlock, UserScheduleSettings
from templates_mgr.admin import RuleAdmin, TemplateAdmin


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.fixture
def admin_request(request_factory, admin_user):
    request = request_factory.get("/admin/")
    request.user = admin_user
    return request


@pytest.mark.django_db
class TestScheduleAdmin:
    @pytest.mark.parametrize("admin_type, model", [
        (ScheduleAdmin, Schedule),
        (TimeBlockAdmin, TimeBlock),
        (UserScheduleSettingsAdmin, UserScheduleSettings),
    ])
    def test_day_and_policy_admin_surfaces_are_inspection_only(
        self, admin_request, admin_type, model
    ):
        admin = admin_type(model, AdminSite())
        assert admin.has_view_permission(admin_request) is True
        assert admin.has_add_permission(admin_request) is False
        assert admin.has_change_permission(admin_request) is False
        assert admin.has_delete_permission(admin_request) is False

    def test_block_count_annotation(self, admin_request):
        schedule = Schedule.objects.create(date=datetime.date(2026, 5, 1), user=admin_request.user)
        schedule.time_blocks.create(title="A", start_time="09:00", end_time="10:00")
        schedule.time_blocks.create(title="B", start_time="10:00", end_time="11:00")

        admin = ScheduleAdmin(Schedule, AdminSite())
        qs = admin.get_queryset(admin_request)
        obj = qs.get(pk=schedule.pk)
        assert admin.block_count(obj) == 2

    @pytest.mark.parametrize("with_block", [False, True])
    def test_inspection_page_renders_without_allowing_writes(self, admin_client, user, with_block):
        schedule = Schedule.objects.create(
            user=user, date=datetime.date(2027, 11, 10), status="active", revision=8
        )
        if with_block:
            schedule.time_blocks.create(
                title="Inspection anchor", category="work", start_time="09:00", end_time="09:30"
            )
        url = reverse("admin:schedules_schedule_change", args=[schedule.pk])
        response = admin_client.get(url)
        assert response.status_code == 200
        if with_block:
            assert b"Inspection anchor" in response.content
        assert admin_client.post(url, {"status": "draft", "_save": "Save"}).status_code == 403
        schedule.refresh_from_db()
        assert schedule.status == "active" and schedule.revision == 8
        assert schedule.time_blocks.count() == int(with_block)


@pytest.mark.django_db
class TestAIInteractionAdmin:
    def test_view_only(self, admin_request):
        admin = AIInteractionAdmin(AIInteraction, AdminSite())
        assert admin.has_add_permission(admin_request) is False
        assert admin.has_change_permission(admin_request) is False
        assert admin.has_delete_permission(admin_request) is False


@pytest.mark.django_db
class TestAdminRegistration:
    """Smoke test: all admin classes instantiate without error."""

    def test_all_admins_instantiate(self):
        from analytics.models import DailyReview
        from schedules.models import TimeBlock
        from templates_mgr.models import Rule, Template

        site = AdminSite()
        ScheduleAdmin(Schedule, site)
        TimeBlockAdmin(TimeBlock, site)
        TemplateAdmin(Template, site)
        RuleAdmin(Rule, site)
        AIInteractionAdmin(AIInteraction, site)
        DailyReviewAdmin(DailyReview, site)


@pytest.mark.django_db
def test_preferences_admin_and_inline_inspection_only(admin_request):
    from django.contrib.auth import get_user_model
    from templates_mgr.admin import UserPreferencesAdmin, UserPreferencesInline
    from templates_mgr.models import UserPreferences

    for surface in [UserPreferencesAdmin(UserPreferences, AdminSite()),
                    UserPreferencesInline(get_user_model(), AdminSite())]:
        assert surface.has_view_permission(admin_request)
        assert not surface.has_add_permission(admin_request)
        assert not surface.has_change_permission(admin_request)
        assert not surface.has_delete_permission(admin_request)


@pytest.mark.django_db
@pytest.mark.parametrize("with_preferences", [False, True])
def test_user_admin_preferences_inline_renders_and_rejects_policy_writes(
    admin_client, user, admin_request, with_preferences,
):
    from django.contrib.auth import get_user_model
    from templates_mgr.admin import UserPreferencesInline
    from templates_mgr.models import UserPreferences

    if with_preferences:
        UserPreferences.objects.create(user=user, theme="strategic", default_block_gap_minutes=20)
    before = list(UserPreferences.objects.filter(user=user).values())
    add_url = reverse("admin:auth_user_add")
    change_url = reverse("admin:auth_user_change", args=[user.pk])
    assert admin_client.get(add_url).status_code == 200
    response = admin_client.get(change_url)
    assert response.status_code == 200
    inline = UserPreferencesInline(get_user_model(), AdminSite())
    assert inline.has_add_permission(admin_request, user) is False
    assert inline.has_change_permission(admin_request, user) is False
    assert inline.has_delete_permission(admin_request, user) is False

    data = {
        "username": user.username, "is_active": "on", "_save": "Save",
        "date_joined_0": user.date_joined.strftime("%Y-%m-%d"),
        "date_joined_1": user.date_joined.strftime("%H:%M:%S"),
        "preferences-TOTAL_FORMS": "1", "preferences-INITIAL_FORMS": str(int(with_preferences)),
        "preferences-MIN_NUM_FORMS": "0", "preferences-MAX_NUM_FORMS": "1",
        "preferences-0-user": str(user.pk), "preferences-0-theme": "classic",
        "preferences-0-default_block_gap_minutes": "0",
    }
    if with_preferences:
        data["preferences-0-id"] = str(before[0]["id"])
    response = admin_client.post(change_url, data)
    assert response.status_code == 302, response.context["adminform"].form.errors
    assert list(UserPreferences.objects.filter(user=user).values()) == before
