from unittest.mock import patch

import pytest
from calendar_sync.models import CalDAVAccount, TravelRule
from django.contrib.auth.models import User
from gcal_sync.models import GoogleCalendarAccount
from habitica_sync.models import HabiticaAccount
from todoist_sync.models import TodoistAccount


@pytest.mark.django_db
def test_schedule_bootstrap_is_user_scoped_and_refreshed_on_next_full_visit(auth_client, user):
    other = User.objects.create_user(username="other", password="password")
    CalDAVAccount.objects.create(
        user=other, apple_id="other@example.com", password_encrypted=b"cipher"
    )
    HabiticaAccount.objects.create(user=other, api_user_id="other", api_token_encrypted=b"cipher")
    TravelRule.objects.create(user=other, keyword="private", order=1)

    def bootstrap():
        response = auth_client.get("/schedule/2026-04-07/", HTTP_X_INERTIA="true")
        assert response.status_code == 200
        return response.json()["props"]["integration_bootstrap"]

    first = bootstrap()
    assert first["user_id"] == user.pk
    assert first["date"] == "2026-04-07"
    assert first["time_zone"] == "UTC"
    assert first["connected"] == {
        "apple": False, "google": False, "todoist": False, "habitica": False
    }
    assert first["travel_rules"] == []

    CalDAVAccount.objects.create(user=user, apple_id="me@example.com", password_encrypted=b"cipher")
    GoogleCalendarAccount.objects.create(
        user=user, google_account_id="google-id", email="me@example.com",
        refresh_token_encrypted=b"cipher",
    )
    TodoistAccount.objects.create(user=user, token_encrypted=b"cipher")
    HabiticaAccount.objects.create(user=user, api_user_id="me", api_token_encrypted=b"cipher")
    rule = TravelRule.objects.create(user=user, keyword="Office", travel_there_minutes=20, order=2)

    second = bootstrap()
    assert second["snapshot_id"] != first["snapshot_id"]
    assert second["connected"] == {"apple": True, "google": True, "todoist": True, "habitica": True}
    assert second["travel_rules"] == [{
        "id": rule.pk, "keyword": "Office", "calendar_name": "", "travel_there_minutes": 20,
        "travel_back_minutes": 0, "category": "", "order": 2,
    }]


@pytest.mark.django_db
def test_partial_schedule_reload_omits_and_does_not_evaluate_bootstrap(auth_client):
    with patch("schedules.views._integration_bootstrap", side_effect=AssertionError("evaluated")):
        response = auth_client.get(
            "/schedule/2026-04-07/",
            HTTP_X_INERTIA="true",
            HTTP_X_INERTIA_PARTIAL_COMPONENT="Schedule",
            HTTP_X_INERTIA_PARTIAL_DATA="schedule,blocks,date",
        )
    assert response.status_code == 200
    assert "integration_bootstrap" not in response.json()["props"]
