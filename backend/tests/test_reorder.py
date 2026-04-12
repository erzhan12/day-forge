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
def three_blocks(schedule):
    b1 = TimeBlock.objects.create(
        schedule=schedule, title="Morning", start_time="08:00", end_time="09:00", category="work",
    )
    b2 = TimeBlock.objects.create(
        schedule=schedule, title="Standup", start_time="09:00", end_time="09:30", category="work",
    )
    b3 = TimeBlock.objects.create(
        schedule=schedule, title="Deep Work", start_time="10:00", end_time="12:00", category="work",
    )
    return b1, b2, b3


def _post_reorder(client, updates):
    return client.post(
        "/api/blocks/reorder/",
        json.dumps({"updates": updates}),
        content_type="application/json",
    )


class TestReorderBlocks:
    def test_reorder_success(self, auth_client, three_blocks):
        b1, b2, b3 = three_blocks
        resp = _post_reorder(auth_client, [
            {"id": b2.id, "start_time": "07:00", "end_time": "07:30", "sort_order": 0},
            {"id": b1.id, "start_time": "07:30", "end_time": "08:30", "sort_order": 10},
        ])
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["blocks"]) == 3
        # Verify ordering: b2 first (07:00), then b1 (07:30), then b3 (10:00)
        assert data["blocks"][0]["title"] == "Standup"
        assert data["blocks"][0]["start_time"] == "07:00"
        assert data["blocks"][1]["title"] == "Morning"
        assert data["blocks"][1]["start_time"] == "07:30"
        assert data["blocks"][2]["title"] == "Deep Work"

    def test_duplicate_ids_rejected(self, auth_client, three_blocks):
        b1, _, _ = three_blocks
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "08:00", "end_time": "09:00", "sort_order": 0},
            {"id": b1.id, "start_time": "09:00", "end_time": "10:00", "sort_order": 10},
        ])
        assert resp.status_code == 400
        assert "Duplicate" in resp.json()["errors"]["updates"]

    def test_cross_user_rejected(self, auth_client, db):
        other = User.objects.create_user(username="other", password="pass123")
        sched = Schedule.objects.create(date="2026-04-07", user=other)
        block = TimeBlock.objects.create(
            schedule=sched, title="X", start_time="08:00", end_time="09:00", category="work",
        )
        resp = _post_reorder(auth_client, [
            {"id": block.id, "start_time": "10:00", "end_time": "11:00", "sort_order": 0},
        ])
        assert resp.status_code == 403

    def test_cross_schedule_rejected(self, auth_client, user, three_blocks):
        b1, _, _ = three_blocks
        sched2 = Schedule.objects.create(date="2026-04-08", user=user)
        other_block = TimeBlock.objects.create(
            schedule=sched2, title="Y", start_time="08:00", end_time="09:00", category="work",
        )
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "08:00", "end_time": "09:00", "sort_order": 0},
            {"id": other_block.id, "start_time": "09:00", "end_time": "10:00", "sort_order": 10},
        ])
        assert resp.status_code == 400
        assert "same schedule" in resp.json()["errors"]["updates"]

    def test_overlap_with_unchanged_block_rejected(self, auth_client, three_blocks):
        b1, b2, b3 = three_blocks
        # Move b1 to overlap with b3 (10:00-12:00) which is not in the update set
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "10:30", "end_time": "11:30", "sort_order": 0},
        ])
        assert resp.status_code == 400
        assert "overlap" in resp.json()["errors"]["time"].lower()

    def test_invalid_time_format_rejected(self, auth_client, three_blocks):
        b1, _, _ = three_blocks
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "bad", "end_time": "09:00", "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_non_five_minute_time_rejected(self, auth_client, three_blocks):
        b1, _, _ = three_blocks
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "08:03", "end_time": "09:00", "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_start_not_before_end_rejected(self, auth_client, three_blocks):
        b1, _, _ = three_blocks
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "10:00", "end_time": "09:00", "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_invalid_sort_order_rejected(self, auth_client, three_blocks):
        b1, _, _ = three_blocks
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "08:00", "end_time": "09:00", "sort_order": "abc"},
        ])
        assert resp.status_code == 400

    def test_sort_order_out_of_range_rejected(self, auth_client, three_blocks):
        b1, _, _ = three_blocks
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "08:00", "end_time": "09:00", "sort_order": 20000},
        ])
        assert resp.status_code == 400

    def test_atomicity_no_partial_updates(self, auth_client, three_blocks):
        b1, b2, _ = three_blocks
        # b1 update is valid, b2 has invalid time → neither should change
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "07:00", "end_time": "08:00", "sort_order": 0},
            {"id": b2.id, "start_time": "bad", "end_time": "09:30", "sort_order": 10},
        ])
        assert resp.status_code == 400
        # Verify b1 was not changed
        b1.refresh_from_db()
        assert b1.start_time.strftime("%H:%M") == "08:00"

    def test_nonexistent_block_returns_404(self, auth_client, three_blocks):
        resp = _post_reorder(auth_client, [
            {"id": 99999, "start_time": "08:00", "end_time": "09:00", "sort_order": 0},
        ])
        assert resp.status_code == 404

    def test_partial_missing_returns_404_when_truly_absent(
        self, auth_client, three_blocks
    ):
        b1, _, _ = three_blocks
        # b1 is owned by the user; 99999 does not exist anywhere
        resp = _post_reorder(auth_client, [
            {"id": b1.id, "start_time": "07:00", "end_time": "08:00", "sort_order": 0},
            {"id": 99999, "start_time": "08:00", "end_time": "09:00", "sort_order": 10},
        ])
        assert resp.status_code == 404

    def test_other_users_block_alone_returns_403(self, auth_client, db):
        other = User.objects.create_user(username="other2", password="pass123")
        sched = Schedule.objects.create(date="2026-04-09", user=other)
        block = TimeBlock.objects.create(
            schedule=sched, title="Z", start_time="08:00", end_time="09:00",
            category="work",
        )
        resp = _post_reorder(auth_client, [
            {"id": block.id, "start_time": "07:00", "end_time": "08:00", "sort_order": 0},
        ])
        assert resp.status_code == 403

    def test_non_dict_entry_rejected(self, auth_client):
        resp = _post_reorder(auth_client, [1, 2])
        assert resp.status_code == 400
        body = resp.json()
        assert "Entry 0" in body["errors"]["updates"]

    def test_missing_id_rejected(self, auth_client):
        resp = _post_reorder(auth_client, [
            {"start_time": "08:00", "end_time": "09:00", "sort_order": 0},
        ])
        assert resp.status_code == 400
        assert "integer" in resp.json()["errors"]["updates"]

    def test_non_integer_id_rejected(self, auth_client):
        resp = _post_reorder(auth_client, [
            {"id": "abc", "start_time": "08:00", "end_time": "09:00",
             "sort_order": 0},
        ])
        assert resp.status_code == 400

    def test_non_object_body_rejected(self, auth_client):
        for payload in ("[]", "null", '"oops"', "123"):
            resp = auth_client.post(
                "/api/blocks/reorder/",
                payload,
                content_type="application/json",
            )
            assert resp.status_code == 400, f"Expected 400 for body={payload}"
            assert "object" in resp.json()["errors"]["body"].lower()

    def test_empty_updates_rejected(self, auth_client):
        resp = _post_reorder(auth_client, [])
        assert resp.status_code == 400

    def test_unauthenticated_redirects(self, client):
        resp = client.post(
            "/api/blocks/reorder/",
            json.dumps({"updates": []}),
            content_type="application/json",
        )
        assert resp.status_code == 302

    def test_csrf_enforcement(self, csrf_auth_client, three_blocks):
        b1, _, _ = three_blocks
        # POST without CSRF token should fail
        resp = csrf_auth_client.post(
            "/api/blocks/reorder/",
            json.dumps({"updates": [
                {"id": b1.id, "start_time": "07:00", "end_time": "08:00", "sort_order": 0},
            ]}),
            content_type="application/json",
        )
        assert resp.status_code == 403
