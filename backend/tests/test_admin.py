import datetime

import pytest
from ai.admin import AIInteractionAdmin
from ai.models import AIInteraction
from analytics.admin import DailyReviewAdmin
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory
from schedules.admin import ScheduleAdmin, TimeBlockAdmin
from schedules.models import Schedule
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
    def test_block_count_annotation(self, admin_request):
        schedule = Schedule.objects.create(date=datetime.date(2026, 5, 1))
        schedule.time_blocks.create(title="A", start_time="09:00", end_time="10:00")
        schedule.time_blocks.create(title="B", start_time="10:00", end_time="11:00")

        admin = ScheduleAdmin(Schedule, AdminSite())
        qs = admin.get_queryset(admin_request)
        obj = qs.get(pk=schedule.pk)
        assert admin.block_count(obj) == 2


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
