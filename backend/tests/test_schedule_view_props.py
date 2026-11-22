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
from schedules.models import Schedule, UserScheduleSettings
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
class TestExternalTasksPollIntervalProp:
    def test_passes_setting_to_schedule_props(self, auth_inertia_client, settings):
        settings.EXTERNAL_TASKS_POLL_INTERVAL_SECONDS = 30
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        assert resp.status_code == 200
        props = _props(resp)
        assert props["external_tasks_poll_interval"] == 30

    def test_zero_disables_polling(self, auth_inertia_client, settings):
        settings.EXTERNAL_TASKS_POLL_INTERVAL_SECONDS = 0
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        props = _props(resp)
        assert props["external_tasks_poll_interval"] == 0


@pytest.mark.django_db
def test_schedule_window_prop_includes_persisted_time_zone(auth_inertia_client, user):
    UserScheduleSettings.objects.create(
        user=user, day_start=datetime.time(8), day_end=datetime.time(21), time_zone="Asia/Almaty"
    )
    assert _props(auth_inertia_client.get("/schedule/2026-05-04/"))["schedule_window"] == {
        "start": "08:00", "end": "21:00", "time_zone": "Asia/Almaty"
    }


@pytest.mark.django_db
class TestSharedScheduleDayReader:
    """``schedules.reads.read_schedule_day`` still backs the page's own
    bootstrap and block ordering after the 0088 extraction."""

    def test_page_still_reflects_the_shared_reader_block_ordering(
        self, auth_inertia_client, user
    ):
        schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 5, 4))
        schedule.time_blocks.create(
            title="Second", start_time="09:00", end_time="09:15", sort_order=1
        )
        schedule.time_blocks.create(
            title="First", start_time="08:00", end_time="08:15", sort_order=0
        )
        props = _props(auth_inertia_client.get("/schedule/2026-05-04/"))
        assert [b["title"] for b in props["blocks"]] == ["First", "Second"]

    def test_absent_day_still_bootstraps_through_the_page_view(
        self, auth_inertia_client, user
    ):
        resp = auth_inertia_client.get("/schedule/2026-05-04/")
        assert resp.status_code == 200
        assert Schedule.objects.filter(user=user, date=datetime.date(2026, 5, 4)).exists()


@pytest.mark.django_db
def test_blocks_prop_excludes_unimported_calendar_events(auth_inertia_client, user):
    """Feature 0106: a calendar event reaches the timeline only through an
    explicit import. The page view serialises stored blocks and never asks a
    calendar provider for events, even with connected accounts."""
    from unittest.mock import patch

    from calendar_sync.models import CalDAVAccount
    from gcal_sync.models import GoogleCalendarAccount

    CalDAVAccount.objects.create(user=user, apple_id="me@example.com", password_encrypted=b"cipher")
    GoogleCalendarAccount.objects.create(
        user=user, google_account_id="google-id", email="me@example.com",
        refresh_token_encrypted=b"cipher",
    )
    schedule = Schedule.objects.create(user=user, date=datetime.date(2026, 5, 4))
    schedule.time_blocks.create(
        title="Stored", start_time="15:00", end_time="16:00", sort_order=0
    )
    with patch("calendar_sync.service.fetch_events_for_date") as caldav_fetch, patch(
        "gcal_sync.service.fetch_events_for_account"
    ) as google_fetch:
        props = _props(auth_inertia_client.get("/schedule/2026-05-04/"))

    assert [b["title"] for b in props["blocks"]] == ["Stored"]
    assert props["integration_bootstrap"]["connected"]["apple"] is True
    assert props["integration_bootstrap"]["connected"]["google"] is True
    caldav_fetch.assert_not_called()
    google_fetch.assert_not_called()
