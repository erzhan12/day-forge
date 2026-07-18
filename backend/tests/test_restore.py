import json

import pytest
from schedules.models import Schedule, TimeBlock


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

    def test_restore_off_grid_time_accepted(self, auth_client, schedule):
        """Contract flip (feature 0026): restore re-persists previously-
        valid states, which may include off-grid from-event blocks — the
        pre-0026 behavior rejected ``08:03`` with a 400."""
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "X", "start_time": "08:03", "end_time": "09:00", "category": "work",
             "is_completed": False, "sort_order": 0},
        ])
        assert resp.status_code == 200
        block = TimeBlock.objects.get(schedule=schedule, title="X")
        assert block.start_time.strftime("%H:%M") == "08:03"

    def test_restore_off_grid_snapshot_persisted_verbatim(
        self, auth_client, two_blocks, schedule
    ):
        """Full-day undo snapshot containing an off-grid from-event block
        (14:07–14:33) restores every block verbatim — before the 0026
        granularity bypass, undoing *any* edit on such a day 400d."""
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "Morning", "start_time": "08:00", "end_time": "09:00",
             "category": "work", "is_completed": False, "sort_order": 0},
            {"title": "Dentist", "start_time": "14:07", "end_time": "14:33",
             "category": "other", "is_completed": False, "sort_order": 10},
        ])
        assert resp.status_code == 200
        times = {
            b["title"]: (b["start_time"], b["end_time"])
            for b in resp.json()["blocks"]
        }
        assert times["Dentist"] == ("14:07", "14:33")

    def test_restore_off_grid_overlap_still_rejected(self, auth_client, schedule):
        resp = _post_restore(auth_client, "2026-04-07", [
            {"title": "A", "start_time": "14:07", "end_time": "14:33", "category": "other",
             "is_completed": False, "sort_order": 0},
            {"title": "B", "start_time": "14:20", "end_time": "15:00", "category": "work",
             "is_completed": False, "sort_order": 10},
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

    def test_undo_of_add_removes_the_added_block(self, auth_client, two_blocks, schedule):
        """End-to-end verification of the "undo add" flow.

        When the frontend handles an add, it snapshots the block list
        *before* the add and pushes that snapshot onto the undo stack.
        Performing undo POSTs that snapshot to the restore endpoint,
        which replaces the entire schedule — so the just-added block
        vanishes. This test exercises that contract against the real
        endpoint without any frontend involvement.
        """
        b1, b2 = two_blocks
        # ``two_blocks`` creates rows with ``start_time="08:00"`` etc —
        # Django's ``TimeField`` does not coerce the string to
        # ``datetime.time`` until the row is re-fetched from the DB, so
        # we refresh before reading the fields to get consistent types.
        b1.refresh_from_db()
        b2.refresh_from_db()

        def _hhmm(t):
            return t.strftime("%H:%M")

        # Snapshot looks like what the frontend's snapshotBlocks() would
        # produce right before the user clicks "Add block".
        pre_add_snapshot = [
            {
                "title": b1.title,
                "start_time": _hhmm(b1.start_time),
                "end_time": _hhmm(b1.end_time),
                "category": b1.category,
                "is_completed": b1.is_completed,
                "sort_order": b1.sort_order,
            },
            {
                "title": b2.title,
                "start_time": _hhmm(b2.start_time),
                "end_time": _hhmm(b2.end_time),
                "category": b2.category,
                "is_completed": b2.is_completed,
                "sort_order": b2.sort_order,
            },
        ]

        # Simulate the user adding a third block via the normal create
        # endpoint (the same code path the frontend uses).
        add_resp = auth_client.post(
            f"/api/schedules/{schedule.date}/blocks/",
            json.dumps({
                "title": "Just Added",
                "start_time": "11:00",
                "end_time": "12:00",
                "category": "work",
            }),
            content_type="application/json",
        )
        assert add_resp.status_code == 201
        added_id = add_resp.json()["id"]
        assert TimeBlock.objects.filter(id=added_id).exists()
        assert TimeBlock.objects.filter(schedule=schedule).count() == 3

        # Undo: replay the pre-add snapshot via restore. This is exactly
        # what useUndo.performUndo() does when called after an add.
        undo_resp = _post_restore(auth_client, str(schedule.date), pre_add_snapshot)
        assert undo_resp.status_code == 200

        # The added block should be gone, and only the two original
        # titles should remain on the schedule.
        assert not TimeBlock.objects.filter(id=added_id).exists()
        remaining = TimeBlock.objects.filter(schedule=schedule)
        assert remaining.count() == 2
        titles = set(remaining.values_list("title", flat=True))
        assert titles == {b1.title, b2.title}

    def test_oversized_body_rejected(self, auth_client):
        """Bodies over MAX_REQUEST_BODY_BYTES (100 KB) return 413 before
        json.loads even runs, so a malicious client can't force expensive
        parsing of megabytes of JSON via the 2.5 MB Django default."""
        huge_title = "x" * 200_000
        payload = json.dumps({
            "blocks": [{
                "title": huge_title,
                "start_time": "08:00",
                "end_time": "09:00",
                "category": "work",
                "is_completed": False,
                "sort_order": 0,
            }],
        })
        resp = auth_client.post(
            "/api/schedules/2026-04-07/blocks/restore/",
            payload,
            content_type="application/json",
        )
        assert resp.status_code == 413
        assert "too large" in resp.json()["errors"]["body"].lower()

    def test_locks_schedule_row(self, auth_client, schedule, monkeypatch):
        """Regression: ``restore_blocks`` must lock the parent ``Schedule``
        row so it serializes with ``_apply_draft_sync`` on an empty day."""
        from schedules.models import Schedule as _Schedule

        original = _Schedule.objects.select_for_update
        called = {"v": False}

        def _spy(*args, **kwargs):
            called["v"] = True
            return original(*args, **kwargs)

        monkeypatch.setattr(
            _Schedule.objects, "select_for_update", _spy, raising=True
        )
        resp = _post_restore(
            auth_client,
            "2026-04-07",
            [{
                "title": "A",
                "start_time": "10:00",
                "end_time": "11:00",
                "category": "work",
                "is_completed": False,
                "sort_order": 0,
            }],
        )
        assert resp.status_code == 200, resp.content
        assert called["v"]
