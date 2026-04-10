import json

import pytest
from django.contrib.auth.models import User
from django.test import Client
from schedules.models import Schedule, TimeBlock


@pytest.fixture
def user(db):
    return User.objects.create_user(username="testuser", password="testpass123")


@pytest.fixture
def auth_client(user):
    client = Client()
    client.login(username="testuser", password="testpass123")
    return client


@pytest.fixture
def csrf_client():
    return Client(enforce_csrf_checks=True)


@pytest.fixture
def csrf_auth_client(user):
    client = Client(enforce_csrf_checks=True)
    client.login(username="testuser", password="testpass123")
    return client


@pytest.fixture
def schedule(user):
    return Schedule.objects.create(date="2026-04-07", user=user)


@pytest.fixture
def time_block(schedule):
    return TimeBlock.objects.create(
        schedule=schedule,
        title="Deep Work",
        start_time="09:00",
        end_time="10:00",
        category="work",
    )


class TestRootRedirect:
    def test_redirects_to_today(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 302
        assert "/schedule/" in resp.url


class TestLoginView:
    def test_get_returns_200(self, client):
        resp = client.get("/accounts/login/")
        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_post_valid_credentials(self, client, user):
        resp = client.post(
            "/accounts/login/",
            {"username": "testuser", "password": "testpass123"},
        )
        assert resp.status_code == 302
        assert "/schedule/" in resp.url

    @pytest.mark.django_db
    def test_post_invalid_credentials(self, client, user):
        resp = client.post(
            "/accounts/login/",
            {"username": "testuser", "password": "wrong"},
        )
        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_authenticated_user_redirected(self, auth_client):
        resp = auth_client.get("/accounts/login/")
        assert resp.status_code == 302

    @pytest.mark.django_db
    def test_get_sets_csrf_cookie(self, csrf_client):
        resp = csrf_client.get("/accounts/login/")
        assert resp.status_code == 200
        assert "XSRF-TOKEN" in resp.cookies

    @pytest.mark.django_db
    def test_post_with_csrf_token(self, csrf_client, user):
        # GET first to obtain CSRF cookie
        resp = csrf_client.get("/accounts/login/")
        csrf_token = resp.cookies["XSRF-TOKEN"].value
        # POST with CSRF token in header
        resp = csrf_client.post(
            "/accounts/login/",
            {"username": "testuser", "password": "testpass123"},
            headers={"X-XSRF-TOKEN": csrf_token},
        )
        assert resp.status_code == 302
        assert "/schedule/" in resp.url


class TestLogoutView:
    @pytest.mark.django_db
    def test_logout_redirects(self, auth_client):
        resp = auth_client.post("/accounts/logout/")
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url

    @pytest.mark.django_db
    def test_unauthenticated_logout_redirects_to_login(self, client):
        resp = client.post("/accounts/logout/")
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url


class TestScheduleView:
    @pytest.mark.django_db
    def test_unauthenticated_redirects(self, client):
        resp = client.get("/schedule/2026-04-07/")
        assert resp.status_code == 302
        assert "/accounts/login/" in resp.url

    @pytest.mark.django_db
    def test_authenticated_returns_200(self, auth_client):
        resp = auth_client.get("/schedule/2026-04-07/")
        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_creates_schedule_if_missing(self, auth_client):
        auth_client.get("/schedule/2026-01-15/")
        assert Schedule.objects.filter(date="2026-01-15").exists()

    @pytest.mark.django_db
    def test_invalid_date_returns_400(self, auth_client):
        resp = auth_client.get("/schedule/not-a-date/")
        assert resp.status_code == 400


class TestCreateBlock:
    @pytest.mark.django_db
    def test_creates_block(self, auth_client, schedule):
        resp = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "Meeting",
                "start_time": "14:00",
                "end_time": "15:00",
                "category": "work",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Meeting"
        assert data["start_time"] == "14:00"
        assert TimeBlock.objects.filter(title="Meeting").exists()

    @pytest.mark.django_db
    def test_invalid_time_returns_400(self, auth_client, schedule):
        resp = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "Bad",
                "start_time": "14:03",
                "end_time": "15:00",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_unauthenticated_returns_302(self, client):
        resp = client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({"title": "X", "start_time": "09:00", "end_time": "10:00"}),
            content_type="application/json",
        )
        assert resp.status_code == 302

    @pytest.mark.django_db
    def test_spans_midnight_rejected(self, auth_client, schedule):
        # TimeField has no date component, so 23:00→01:00 fails start<end check
        resp = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "Midnight",
                "start_time": "23:00",
                "end_time": "01:00",
                "category": "other",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "time" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_title_at_max_length_accepted(self, auth_client, schedule):
        resp = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "A" * 255,
                "start_time": "14:00",
                "end_time": "15:00",
                "category": "work",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 201

    @pytest.mark.django_db
    def test_title_over_max_length_rejected(self, auth_client, schedule):
        resp = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "A" * 256,
                "start_time": "14:00",
                "end_time": "15:00",
                "category": "work",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "title" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_adjacent_blocks_allowed(self, auth_client, schedule):
        resp1 = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "First",
                "start_time": "09:00",
                "end_time": "10:00",
                "category": "work",
            }),
            content_type="application/json",
        )
        assert resp1.status_code == 201
        resp2 = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "Second",
                "start_time": "10:00",
                "end_time": "11:00",
                "category": "work",
            }),
            content_type="application/json",
        )
        assert resp2.status_code == 201

    @pytest.mark.django_db
    def test_overlapping_block_returns_400(self, auth_client, time_block):
        resp = auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "Overlap",
                "start_time": "09:30",
                "end_time": "10:30",
                "category": "work",
            }),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "overlap" in resp.json()["errors"]["time"].lower()

    @pytest.mark.django_db
    def test_create_with_csrf_token(self, csrf_auth_client, schedule):
        # GET login page to obtain CSRF cookie
        resp = csrf_auth_client.get("/accounts/login/")
        csrf_token = resp.cookies["XSRF-TOKEN"].value
        resp = csrf_auth_client.post(
            "/api/schedules/2026-04-07/blocks/",
            json.dumps({
                "title": "CSRF Test",
                "start_time": "14:00",
                "end_time": "15:00",
            }),
            content_type="application/json",
            headers={"X-XSRF-TOKEN": csrf_token},
        )
        assert resp.status_code == 201


class TestBlockDetail:
    @pytest.mark.django_db
    def test_update_title(self, auth_client, time_block):
        resp = auth_client.patch(
            f"/api/blocks/{time_block.pk}/",
            json.dumps({"title": "Updated"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated"
        time_block.refresh_from_db()
        assert time_block.title == "Updated"

    @pytest.mark.django_db
    def test_toggle_completed(self, auth_client, time_block):
        resp = auth_client.patch(
            f"/api/blocks/{time_block.pk}/",
            json.dumps({"is_completed": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["is_completed"] is True

    @pytest.mark.django_db
    def test_delete_block(self, auth_client, time_block):
        resp = auth_client.delete(f"/api/blocks/{time_block.pk}/")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert not TimeBlock.objects.filter(pk=time_block.pk).exists()

    @pytest.mark.django_db
    def test_update_malformed_time_returns_400(self, auth_client, time_block):
        resp = auth_client.patch(
            f"/api/blocks/{time_block.pk}/",
            json.dumps({"start_time": "bad"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "errors" in resp.json()

    @pytest.mark.django_db
    def test_delete_nonexistent_returns_404(self, auth_client):
        resp = auth_client.delete("/api/blocks/99999/")
        assert resp.status_code == 404

    @pytest.mark.django_db
    def test_cannot_patch_other_users_block(self, auth_client):
        other = User.objects.create_user(username="other", password="pass")
        other_schedule = Schedule.objects.create(date="2026-04-07", user=other)
        block = TimeBlock.objects.create(
            schedule=other_schedule, title="X", start_time="09:00", end_time="10:00"
        )
        resp = auth_client.patch(
            f"/api/blocks/{block.pk}/",
            json.dumps({"title": "Hacked"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_cannot_delete_other_users_block(self, auth_client):
        other = User.objects.create_user(username="other", password="pass")
        other_schedule = Schedule.objects.create(date="2026-04-07", user=other)
        block = TimeBlock.objects.create(
            schedule=other_schedule, title="X", start_time="09:00", end_time="10:00"
        )
        resp = auth_client.delete(f"/api/blocks/{block.pk}/")
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_patch_without_csrf_token_rejected(self, csrf_client, user, time_block):
        csrf_client.login(username="testuser", password="testpass123")
        resp = csrf_client.patch(
            f"/api/blocks/{time_block.pk}/",
            json.dumps({"title": "No CSRF"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_delete_without_csrf_token_rejected(self, csrf_client, user, time_block):
        csrf_client.login(username="testuser", password="testpass123")
        resp = csrf_client.delete(f"/api/blocks/{time_block.pk}/")
        assert resp.status_code == 403

    @pytest.mark.django_db
    def test_patch_invalid_category_rejected(self, auth_client, time_block):
        resp = auth_client.patch(
            f"/api/blocks/{time_block.pk}/",
            json.dumps({"category": "not-a-category"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "category" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_patch_sort_order_non_integer_rejected(self, auth_client, time_block):
        resp = auth_client.patch(
            f"/api/blocks/{time_block.pk}/",
            json.dumps({"sort_order": "first"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "sort_order" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_patch_sort_order_out_of_bounds_rejected(self, auth_client, time_block):
        resp = auth_client.patch(
            f"/api/blocks/{time_block.pk}/",
            json.dumps({"sort_order": 2147483647}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "sort_order" in resp.json()["errors"]

    @pytest.mark.django_db
    def test_patch_sort_order_valid(self, auth_client, time_block):
        resp = auth_client.patch(
            f"/api/blocks/{time_block.pk}/",
            json.dumps({"sort_order": 5}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["sort_order"] == 5
