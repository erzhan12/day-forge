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
def csrf_auth_client(user):
    client = Client(enforce_csrf_checks=True)
    client.login(username="testuser", password="testpass123")
    return client


@pytest.fixture
def schedule(user):
    return Schedule.objects.create(date="2026-04-07", user=user)


@pytest.fixture
def two_blocks(schedule):
    b1 = TimeBlock.objects.create(
        schedule=schedule, title="Morning", start_time="08:00", end_time="09:00", category="work",
    )
    b2 = TimeBlock.objects.create(
        schedule=schedule, title="Standup", start_time="09:00", end_time="09:30", category="work",
    )
    return b1, b2


def _post_restore(client, date, blocks):
    return client.post(
        f"/api/schedules/{date}/blocks/restore/",
        json.dumps({"blocks": blocks}),
        content_type="application/json",
    )


class TestRestoreBlocks:
    def test_restore_replaces_all_blocks(self, auth_client, two_blocks, schedule):
        new_blocks = [
            {"title": "A", "start_time": "10:00", "end_time": "11:00", "category": "personal",
             "is_completed": False, "sort_order": 0},
            {"title": "B", "start_time": "11:00", "end_time": "12:00", "category": "health",
             "is_completed": True, "sort_order": 10},
            {"title": "C", "start_time": "13:00", "end_time": "14:00", "category": "other",
             "is_completed": False, "sort_order": 20},
        ]
        resp = _post_restore(auth_client, "2026-04-07", new_blocks)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["blocks"]) == 3
        assert data["blocks"][0]["title"] == "A"
        assert data["blocks"][1]["title"] == "B"
        assert data["blocks"][1]["is_completed"] is True
        assert data["blocks"][2]["title"] == "C"
        # Old blocks gone
        assert not TimeBlock.objects.filter(title="Morning").exists()
        assert not TimeBlock.objects.filter(title="Standup").exists()

    def test_restore_empty_deletes_all(self, auth_client, two_blocks, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [])
        assert resp.status_code == 200
        assert len(resp.json()["blocks"]) == 0
        assert TimeBlock.objects.filter(schedule=schedule).count() == 0

    def test_restore_preserves_other_schedule(self, auth_client, user, two_blocks):
        other_sched = Schedule.objects.create(date="2026-04-08", user=user)
        TimeBlock.objects.create(
            schedule=other_sched, title="Other",
            start_time="08:00", end_time="09:00", category="work",
        )
        # Restore on a different date
        resp = _post_restore(auth_client, "2026-04-07", [])
        assert resp.status_code == 200
        # Other schedule's block still exists
        assert TimeBlock.objects.filter(schedule=other_sched).count() == 1

    def test_restore_invalid_category_rejected(self, auth_client, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "X", "start_time": "08:00", "end_time": "09:00", "category": "invalid",
             "is_completed": False, "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_restore_empty_title_rejected(self, auth_client, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "", "start_time": "08:00", "end_time": "09:00", "category": "work",
             "is_completed": False, "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_restore_invalid_times_rejected(self, auth_client, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "X", "start_time": "bad", "end_time": "09:00", "category": "work",
             "is_completed": False, "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_restore_non_five_minute_time_rejected(self, auth_client, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "X", "start_time": "08:03", "end_time": "09:00", "category": "work",
             "is_completed": False, "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_restore_start_not_before_end_rejected(self, auth_client, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "X", "start_time": "10:00", "end_time": "09:00", "category": "work",
             "is_completed": False, "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_restore_overlapping_blocks_rejected(self, auth_client, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "A", "start_time": "08:00", "end_time": "09:30", "category": "work",
             "is_completed": False, "sort_order": 0},
            {"title": "B", "start_time": "09:00", "end_time": "10:00", "category": "work",
             "is_completed": False, "sort_order": 10},
        ])
        assert resp.status_code == 400

    def test_restore_non_dict_entry_rejected(self, auth_client, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [1, "abc"])
        assert resp.status_code == 400
        body = resp.json()
        assert "Entry 0" in body["errors"]["blocks"]

    def test_restore_atomicity(self, auth_client, two_blocks, schedule):
        # First block valid, second has empty title → neither should apply
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "Valid", "start_time": "08:00", "end_time": "09:00", "category": "work",
             "is_completed": False, "sort_order": 0},
            {"title": "", "start_time": "09:00", "end_time": "10:00", "category": "work",
             "is_completed": False, "sort_order": 10},
        ])
        assert resp.status_code == 400
        # Original blocks still intact
        assert TimeBlock.objects.filter(schedule=schedule).count() == 2
        assert TimeBlock.objects.filter(title="Morning").exists()

    def test_restore_creates_schedule_if_missing(self, auth_client, user):
        # No schedule for this date yet
        resp = _post_restore(auth_client, "2026-04-15", [
            {"title": "New", "start_time": "08:00", "end_time": "09:00", "category": "work",
             "is_completed": False, "sort_order": 0},
        ])
        assert resp.status_code == 200
        assert Schedule.objects.filter(user=user, date="2026-04-15").exists()

    def test_restore_invalid_date_rejected(self, auth_client):
        resp = _post_restore(auth_client, "not-a-date", [])
        assert resp.status_code == 400

    def test_non_object_body_rejected(self, auth_client):
        for payload in ("[]", "null", '"oops"', "123"):
            resp = auth_client.post(
                "/api/schedules/2026-04-07/blocks/restore/",
                payload,
                content_type="application/json",
            )
            assert resp.status_code == 400, f"Expected 400 for body={payload}"
            assert "object" in resp.json()["errors"]["body"].lower()

    def test_unauthenticated_redirects(self, client):
        resp = client.post(
            "/api/schedules/2026-04-07/blocks/restore/",
            json.dumps({"blocks": []}),
            content_type="application/json",
        )
        assert resp.status_code == 302

    def test_csrf_enforcement(self, csrf_auth_client, schedule):
        resp = csrf_auth_client.post(
            "/api/schedules/2026-04-07/blocks/restore/",
            json.dumps({"blocks": []}),
            content_type="application/json",
        )
        assert resp.status_code == 403
