import json

import pytest
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/schedule/{date}/", "/settings/", "/analytics/{date}/"])
def test_authenticated_pages_encrypt_browser_history(client, user, schedule, path):
    client.force_login(user)
    response = client.get(path.format(date=schedule.date), HTTP_X_INERTIA="true")
    assert response.status_code == 200
    assert response.json()["encryptHistory"] is True


@pytest.mark.django_db
def test_logout_login_response_invalidates_private_history(client, user, schedule):
    client.force_login(user)
    client.get(f"/schedule/{schedule.date}/", HTTP_X_INERTIA="true")
    response = client.post("/accounts/logout/", follow=True, HTTP_X_INERTIA="true")
    page = response.json()
    assert page["component"] == "Login"
    assert page["props"]["auth_user_id"] is None
    assert page["encryptHistory"] is True
    assert page["clearHistory"] is True
    denied = client.get(f"/schedule/{schedule.date}/")
    assert denied.status_code == 302
    assert "/accounts/login/" in denied.url


@pytest.mark.django_db
def test_login_after_session_expiry_also_clears_history(client):
    response = client.get("/accounts/login/", HTTP_X_INERTIA="true")
    assert response.json()["clearHistory"] is True


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


@pytest.mark.django_db
def test_old_session_identity_header_does_not_block_get(client, user, schedule):
    client.force_login(user)

    response = client.get(
        f"/api/schedules/{schedule.date}/blocks/",
        HTTP_X_SCHEDULE_USER="99999",
    )

    # The view only accepts POST. Reaching its method guard proves the
    # identity middleware excludes reads from the stale-session check.
    assert response.status_code == 405


@pytest.mark.django_db
def test_identity_header_on_unauthenticated_write_returns_session_invalid(client, schedule):
    response = client.post(
        f"/api/schedules/{schedule.date}/blocks/",
        json.dumps({"title": "Must not be created"}),
        content_type="application/json",
        HTTP_X_SCHEDULE_USER="12345",
    )

    assert response.status_code == 401
    assert response.json()["code"] == "session_invalid"
    assert not TimeBlock.objects.filter(schedule=schedule).exists()
