"""Feature 0053 (Slices 4 & 6) — HTTP-boundary day-window enforcement.

The pure ``clamp_boundary`` / ``ScheduleWindow`` unit coverage lives in
``test_schedule_window.py``; this file exercises the *wirings* of that clamp
into the four schedule-mutation endpoints:

* ``create_block``            — fully-outside skip, partial clamp, inside pass-through.
* ``create_block_from_event`` — the off-grid create path clamps/skips the same way.
* ``block_detail`` (PATCH)    — only the *changed* boundary is clamped; the
  inherited (possibly legacy out-of-window / off-grid) boundary is preserved,
  and metadata-only PATCHes never revalidate stored times.
* ``reorder_blocks``          — an outside row aborts the *whole* batch (no
  partial commit).

The stable skip envelope is ``_outside_window_response`` — a 422 with
top-level ``skipped``/``code``/``window`` siblings.

Custom windows are installed by writing ``UserScheduleSettings`` directly
(``get_schedule_window`` reads it via ``get_or_create``). Legacy stored blocks
that predate a window change are seeded straight through the ORM so the
create-time clamp doesn't rewrite them first.
"""
import datetime
import json

import pytest
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock, UserScheduleSettings

CREATE_URL = "/api/schedules/2026-04-07/blocks/"
FROM_EVENT_URL = "/api/schedules/2026-04-07/blocks/from-event/"


def _post_create(client, body, url=CREATE_URL):
    return client.post(url, json.dumps(body), content_type="application/json")


def _post_from_event(client, body, url=FROM_EVENT_URL):
    return client.post(url, json.dumps(body), content_type="application/json")


def _patch_block(client, pk, body):
    return client.patch(
        f"/api/blocks/{pk}/", json.dumps(body), content_type="application/json"
    )


def _post_reorder(client, updates):
    return client.post(
        "/api/blocks/reorder/",
        json.dumps({"updates": updates}),
        content_type="application/json",
    )


def _set_window(user, start, end):
    """Force a user's window; ``get_schedule_window`` reads this row."""
    UserScheduleSettings.objects.update_or_create(
        user=user,
        defaults={
            "day_start": datetime.time.fromisoformat(start),
            "day_end": datetime.time.fromisoformat(end),
        },
    )


def _assert_skip_envelope(resp, window_start="06:00", window_end="23:00"):
    """Assert the exact ``_outside_window_response`` contract."""
    assert resp.status_code == 422, resp.content
    body = resp.json()
    # Top-level siblings — NOT nested under ``errors``.
    assert body["skipped"] is True
    assert body["code"] == "outside_window"
    assert body["window"] == {"start": window_start, "end": window_end}
    # The human-readable duplicates are also present but the machine contract
    # above is what the frontend keys on.
    assert body["errors"]["time"] == "Block is outside your day window."


class TestCreateBlockWindow:
    """``create_block`` — default 06:00–23:00 window."""

    @pytest.mark.django_db
    def test_fully_outside_returns_skip_contract_and_creates_nothing(
        self, auth_client, schedule
    ):
        resp = _post_create(
            auth_client,
            {"title": "Pre-dawn", "start_time": "04:00", "end_time": "05:00"},
        )
        _assert_skip_envelope(resp)
        assert TimeBlock.objects.filter(schedule=schedule).count() == 0

    @pytest.mark.django_db
    def test_partially_outside_clamps_to_boundary(self, auth_client, schedule):
        # 05:00–07:00 straddles the 06:00 day_start -> clamps to 06:00–07:00.
        resp = _post_create(
            auth_client,
            {"title": "Early", "start_time": "05:00", "end_time": "07:00"},
        )
        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert data["start_time"] == "06:00"
        assert data["end_time"] == "07:00"

    @pytest.mark.django_db
    def test_partially_outside_late_end_clamps_to_day_end(
        self, auth_client, schedule
    ):
        # 22:00–23:30 straddles 23:00 day_end -> clamps end to 23:00.
        resp = _post_create(
            auth_client,
            {"title": "Late", "start_time": "22:00", "end_time": "23:30"},
        )
        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert data["start_time"] == "22:00"
        assert data["end_time"] == "23:00"

    @pytest.mark.django_db
    def test_fully_inside_unchanged(self, auth_client, schedule):
        resp = _post_create(
            auth_client,
            {"title": "Midday", "start_time": "09:00", "end_time": "10:00"},
        )
        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert data["start_time"] == "09:00"
        assert data["end_time"] == "10:00"

    @pytest.mark.django_db
    def test_custom_window_skip_envelope_echoes_custom_bounds(
        self, auth_client, user, schedule
    ):
        _set_window(user, "08:00", "20:00")
        resp = _post_create(
            auth_client,
            {"title": "Too early", "start_time": "06:00", "end_time": "07:00"},
        )
        _assert_skip_envelope(resp, window_start="08:00", window_end="20:00")
        assert TimeBlock.objects.filter(schedule=schedule).count() == 0

    @pytest.mark.django_db
    def test_multi_user_isolation_on_skip_path(self, auth_client, user):
        """A second user's block on the same date must be unaffected by the
        skip; the skip is scoped to the requesting user's own schedule."""
        other = User.objects.create_user(username="other", password="pass123")
        other_sched = Schedule.objects.create(date="2026-04-07", user=other)
        other_block = TimeBlock.objects.create(
            schedule=other_sched, title="Theirs",
            start_time="04:00", end_time="05:00", category="work",
        )
        # Requesting user skips a fully-outside create.
        resp = _post_create(
            auth_client,
            {"title": "Mine", "start_time": "04:00", "end_time": "05:00"},
        )
        _assert_skip_envelope(resp)
        # The other user's block (identical off-window times, seeded via ORM)
        # is untouched, and no block landed on the requesting user's schedule.
        other_block.refresh_from_db()
        assert other_block.start_time.strftime("%H:%M") == "04:00"
        assert not TimeBlock.objects.filter(
            schedule__user=user, title="Mine"
        ).exists()


class TestCreateBlockFromEventWindow:
    """``create_block_from_event`` — off-grid create path, default window.

    These are the ADD cases the plan mandated on top of the 00:00–23:59
    clamp already covered in ``test_from_event.py``.
    """

    @pytest.mark.django_db
    def test_fully_outside_skipped(self, auth_client, schedule):
        # 00:00–00:30 is wholly before the 06:00 day_start -> skip.
        resp = _post_from_event(
            auth_client,
            {"title": "Midnight", "start_time": "00:00", "end_time": "00:30",
             "category": "other"},
        )
        _assert_skip_envelope(resp)
        assert TimeBlock.objects.filter(schedule=schedule).count() == 0

    @pytest.mark.django_db
    def test_partially_outside_clamps_start_to_day_start(
        self, auth_client, schedule
    ):
        # 00:00–07:00 straddles 06:00 -> start clamps to 06:00, end kept.
        resp = _post_from_event(
            auth_client,
            {"title": "Red-eye", "start_time": "00:00", "end_time": "07:00",
             "category": "other"},
        )
        assert resp.status_code == 201, resp.content
        data = resp.json()
        assert data["start_time"] == "06:00"
        assert data["end_time"] == "07:00"


class TestPatchBlockWindow:
    """``block_detail`` PATCH — clamp only the *changed* boundary."""

    @pytest.mark.django_db
    def test_changed_boundary_clamps_unchanged_inherited_boundary_preserved(
        self, auth_client, user
    ):
        """Plan example: stored 05:00–07:00, window 08:00–23:00,
        PATCH end_time=08:00 -> result 05:00–08:00 (start untouched, NOT
        rewritten to the window's 08:00 day_start)."""
        _set_window(user, "08:00", "23:00")
        sched = Schedule.objects.create(date="2026-04-09", user=user)
        # Seed a legacy on-grid but out-of-window block directly via the ORM;
        # create_block would have clamped 05:00 up to 08:00.
        block = TimeBlock.objects.create(
            schedule=sched, title="Legacy",
            start_time="05:00", end_time="07:00", category="work",
        )
        resp = _patch_block(auth_client, block.pk, {"end_time": "08:00"})
        assert resp.status_code == 200, resp.content
        block.refresh_from_db()
        # Start preserved (inherited boundary not clamped), end at the boundary.
        assert block.start_time.strftime("%H:%M") == "05:00"
        assert block.end_time.strftime("%H:%M") == "08:00"

    @pytest.mark.django_db
    def test_metadata_only_patch_does_not_revalidate_stored_times(
        self, auth_client, user
    ):
        """A title/category/completion PATCH on a legacy out-of-window,
        off-grid block succeeds without touching (or revalidating) the
        stored times."""
        _set_window(user, "08:00", "20:00")
        sched = Schedule.objects.create(date="2026-04-09", user=user)
        # Off-grid AND out-of-window — a from-event-style legacy block.
        block = TimeBlock.objects.create(
            schedule=sched, title="Dentist",
            start_time="05:07", end_time="06:33", category="other",
        )
        resp = _patch_block(
            auth_client,
            block.pk,
            {"title": "Dentist (renamed)", "category": "health",
             "is_completed": True},
        )
        assert resp.status_code == 200, resp.content
        block.refresh_from_db()
        assert block.title == "Dentist (renamed)"
        assert block.category == "health"
        assert block.is_completed is True
        # Stored times untouched, not clamped into the 08:00–20:00 window.
        assert block.start_time.strftime("%H:%M") == "05:07"
        assert block.end_time.strftime("%H:%M") == "06:33"

    @pytest.mark.django_db
    def test_changed_boundary_jumping_past_far_edge_skipped(
        self, auth_client, user
    ):
        """A changed start that lands entirely past the opposite bound
        (start 23:35 under a 06:00–23:00 window) is skipped, not accepted —
        clamp_boundary returns None because start > day_end."""
        _set_window(user, "06:00", "23:00")
        sched = Schedule.objects.create(date="2026-04-09", user=user)
        block = TimeBlock.objects.create(
            schedule=sched, title="Evening",
            start_time="21:00", end_time="22:00", category="work",
        )
        resp = _patch_block(auth_client, block.pk, {"start_time": "23:35"})
        _assert_skip_envelope(resp)
        block.refresh_from_db()
        # Unchanged on the skip path.
        assert block.start_time.strftime("%H:%M") == "21:00"
        assert block.end_time.strftime("%H:%M") == "22:00"

    @pytest.mark.django_db
    def test_changed_start_partially_outside_clamps_to_day_start(
        self, auth_client, user
    ):
        _set_window(user, "06:00", "23:00")
        sched = Schedule.objects.create(date="2026-04-09", user=user)
        # Legacy block starting before the window; PATCH start to a still-early
        # but on-grid 05:30 -> clamps up to 06:00, end (already inside) kept.
        block = TimeBlock.objects.create(
            schedule=sched, title="Legacy",
            start_time="05:00", end_time="08:00", category="work",
        )
        resp = _patch_block(auth_client, block.pk, {"start_time": "05:30"})
        assert resp.status_code == 200, resp.content
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "06:00"
        assert block.end_time.strftime("%H:%M") == "08:00"


class TestReorderWindow:
    """``reorder_blocks`` — an outside row aborts the whole batch."""

    @pytest.mark.django_db
    def test_outside_row_aborts_whole_batch(self, auth_client, user, schedule):
        """One row clamping to None (fully outside) returns the skip contract
        and commits NOTHING — the other row's legal move is rolled back."""
        _set_window(user, "06:00", "23:00")
        b1 = TimeBlock.objects.create(
            schedule=schedule, title="Morning",
            start_time="08:00", end_time="09:00", category="work",
        )
        b2 = TimeBlock.objects.create(
            schedule=schedule, title="Deep Work",
            start_time="10:00", end_time="12:00", category="work",
        )
        resp = _post_reorder(
            auth_client,
            [
                # Legal move for b1.
                {"id": b1.id, "start_time": "07:00", "end_time": "07:30",
                 "sort_order": 0},
                # b2 fully outside the window (before day_start) -> None -> abort.
                {"id": b2.id, "start_time": "04:00", "end_time": "05:00",
                 "sort_order": 10},
            ],
        )
        _assert_skip_envelope(resp)
        # No partial commit: b1 keeps its original time, b2 unchanged too.
        b1.refresh_from_db()
        b2.refresh_from_db()
        assert b1.start_time.strftime("%H:%M") == "08:00"
        assert b1.end_time.strftime("%H:%M") == "09:00"
        assert b2.start_time.strftime("%H:%M") == "10:00"
        assert b2.end_time.strftime("%H:%M") == "12:00"

    @pytest.mark.django_db
    def test_partial_row_clamps_when_inside_batch_all_legal(
        self, auth_client, user, schedule
    ):
        """Sanity companion: a batch where a changed boundary merely straddles
        the edge clamps that row and commits (contrast with the abort above)."""
        _set_window(user, "06:00", "23:00")
        b1 = TimeBlock.objects.create(
            schedule=schedule, title="Early",
            start_time="08:00", end_time="09:00", category="work",
        )
        resp = _post_reorder(
            auth_client,
            # Move b1 to straddle day_start: 05:00–07:00 -> clamps to 06:00–07:00.
            [{"id": b1.id, "start_time": "05:00", "end_time": "07:00",
              "sort_order": 0}],
        )
        assert resp.status_code == 200, resp.content
        b1.refresh_from_db()
        assert b1.start_time.strftime("%H:%M") == "06:00"
        assert b1.end_time.strftime("%H:%M") == "07:00"
