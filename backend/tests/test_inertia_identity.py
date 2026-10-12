import json

import pytest
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock


@pytest.mark.django_db
def test_page_identity_changes_with_session(client, user, schedule):
    headers = {"HTTP_X_INERTIA": "true"}
    login = client.get("/accounts/login/", **headers)
    assert login.json()["props"]["auth_user_id"] is None
    client.force_login(user)
    page = client.get(f"/schedule/{schedule.date}/", **headers)
    assert page.json()["props"]["auth_user_id"] == user.pk
    partial = client.get(
        f"/schedule/{schedule.date}/", **headers,
        HTTP_X_INERTIA_PARTIAL_COMPONENT="Schedule",
        HTTP_X_INERTIA_PARTIAL_DATA="schedule,blocks,auth_user_id",
    )
    assert partial.json()["props"]["auth_user_id"] == user.pk
    client.post("/accounts/logout/")
    login = client.get("/accounts/login/", **headers)
    assert login.json()["props"]["auth_user_id"] is None


@pytest.mark.django_db
def test_old_tab_cannot_restore_into_a_new_session_with_same_revision(client, user, schedule):
    other = User.objects.create_user(username="second-undo-user")
    other_day = Schedule.objects.create(user=other, date=schedule.date)
    TimeBlock.objects.create(
        schedule=other_day, title="Second user's task", category="work",
        start_time="09:00", end_time="10:00",
    )
    client.force_login(other)
    response = client.post(
        f"/api/schedules/{schedule.date}/blocks/restore/",
        json.dumps({"expected_revision": 0, "blocks": []}),
        content_type="application/json", HTTP_X_SCHEDULE_USER=str(user.pk),
    )
    assert response.status_code == 401
    assert response.json()["code"] == "session_invalid"
    assert other_day.time_blocks.get().title == "Second user's task"
    other_day.refresh_from_db()
    assert other_day.revision == 0


@pytest.mark.django_db
def test_current_session_identity_header_allows_normal_write(client, user, schedule):
    client.force_login(user)
    response = client.post(
        f"/api/schedules/{schedule.date}/blocks/restore/",
        json.dumps({"expected_revision": 0, "blocks": []}),
        content_type="application/json", HTTP_X_SCHEDULE_USER=str(user.pk),
    )
    assert response.status_code == 200
