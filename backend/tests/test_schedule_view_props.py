"""Tests for the new ``schedule_view`` Inertia props.

``auto_draft_pending`` is a one-shot signal — true only on the request
that *created* the Schedule row, gated by template existence and
``LLM_API_KEY``. ``has_template_for_type`` is the ongoing capability flag
exposed separately so RegenerateDraftButton can stay accurate beyond the
first page load.
"""
import datetime
import json

import pytest
from schedules.models import Schedule
from templates_mgr.models import Template


def _props(resp):
    """Extract Inertia props from an X-Inertia JSON response."""
    return json.loads(resp.content)["props"]


@pytest.fixture
def auth_inertia_client(auth_client):
    auth_client.defaults["HTTP_X_INERTIA"] = "true"
    return auth_client


@pytest.mark.django_db
class TestAutoDraftPending:
    def test_true_on_first_visit_with_template_and_key(
        self, auth_inertia_client, user, settings
    ):
        settings.LLM_API_KEY = "sk-test"
        Template.objects.create(
            user=user, name="WD", type="weekday", blocks=[]
        )
        # 2026-05-04 is a Monday → weekday slot.
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        assert resp.status_code == 200
        props = _props(resp)
        assert props["auto_draft_pending"] is True
        assert props["has_template_for_type"] is True
        assert props["slot_type"] == "weekday"

    def test_false_on_second_visit(
        self, auth_inertia_client, user, settings
    ):
        settings.LLM_API_KEY = "sk-test"
        Template.objects.create(
            user=user, name="WD", type="weekday", blocks=[]
        )
        # First visit creates the schedule.
        Schedule.objects.create(user=user, date=datetime.date(2026, 5, 4))
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        props = _props(resp)
        assert props["auto_draft_pending"] is False
        # Capability flag still True.
        assert props["has_template_for_type"] is True

    def test_false_without_template(
        self, auth_inertia_client, settings
    ):
        settings.LLM_API_KEY = "sk-test"
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        props = _props(resp)
        assert props["auto_draft_pending"] is False
        assert props["has_template_for_type"] is False

    def test_false_without_api_key(
        self, auth_inertia_client, user, settings
    ):
        settings.LLM_API_KEY = ""
        Template.objects.create(
            user=user, name="WD", type="weekday", blocks=[]
        )
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        props = _props(resp)
        assert props["auto_draft_pending"] is False
        assert props["has_template_for_type"] is True

    def test_weekend_slot_picked_for_saturday(
        self, auth_inertia_client, user, settings
    ):
        settings.LLM_API_KEY = "sk-test"
        Template.objects.create(
            user=user, name="WE", type="weekend", blocks=[]
        )
        # 2026-05-02 is a Saturday.
        resp = auth_inertia_client.get("/schedule/2026-05-02/")
        props = _props(resp)
        assert props["slot_type"] == "weekend"
        assert props["has_template_for_type"] is True
        assert props["auto_draft_pending"] is True


@pytest.mark.django_db
class TestTodoistPollIntervalProp:
    def test_passes_setting_to_schedule_props(self, auth_inertia_client, settings):
        settings.TODOIST_POLL_INTERVAL_SECONDS = 30
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        assert resp.status_code == 200
        props = _props(resp)
        assert props["todoist_poll_interval"] == 30

    def test_default_zero_disables_polling(self, auth_inertia_client, settings):
        settings.TODOIST_POLL_INTERVAL_SECONDS = 0
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        props = _props(resp)
        assert props["todoist_poll_interval"] == 0
