"""Tests for the ``Schedule.status`` flip rules.

The badge contract: every forward-mutating endpoint flips ``draft →
active`` on its first run, and ``restore_blocks`` (the undo target)
explicitly does NOT flip status. ``ai_command`` is covered alongside the
draft tests; the rest live here.
"""
import datetime
import json

import pytest
from schedules.models import Schedule, TimeBlock


@pytest.fixture
def draft_schedule(user):
    return Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4), status=Schedule.Status.DRAFT
    )


@pytest.mark.django_db
class TestMarkActiveIfDraft:
    def test_flips_draft_to_active(self, draft_schedule):
        flipped = draft_schedule.mark_active_if_draft()
        assert flipped is True
        draft_schedule.refresh_from_db()
        assert draft_schedule.status == Schedule.Status.ACTIVE

    def test_no_op_when_active(self, user):
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 5),
            status=Schedule.Status.ACTIVE,
        )
        flipped = s.mark_active_if_draft()
        assert flipped is False
        s.refresh_from_db()
        assert s.status == Schedule.Status.ACTIVE

    def test_no_op_when_reviewed(self, user):
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 6),
            status=Schedule.Status.REVIEWED,
        )
        flipped = s.mark_active_if_draft()
        assert flipped is False
        s.refresh_from_db()
        assert s.status == Schedule.Status.REVIEWED


@pytest.mark.django_db
class TestForwardMutationsFlipStatus:
    def test_create_block_flips(self, auth_client, draft_schedule):
        resp = auth_client.post(
            "/api/schedules/2026-05-04/blocks/",
            json.dumps(
                {
                    "title": "T",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "category": "work",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201
        draft_schedule.refresh_from_db()
        assert draft_schedule.status == Schedule.Status.ACTIVE

    def test_patch_block_flips(self, auth_client, draft_schedule):
        block = TimeBlock.objects.create(
            schedule=draft_schedule,
            title="T",
            start_time="10:00",
            end_time="11:00",
            category="work",
        )
        # Status was flipped by create_block (Schedule was created
        # first, then blocks). Reset for the test.
        draft_schedule.status = Schedule.Status.DRAFT
        draft_schedule.save(update_fields=["status"])

        resp = auth_client.patch(
            f"/api/blocks/{block.id}/",
            json.dumps({"title": "Renamed"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        draft_schedule.refresh_from_db()
        assert draft_schedule.status == Schedule.Status.ACTIVE

    def test_delete_block_flips(self, auth_client, draft_schedule):
        block = TimeBlock.objects.create(
            schedule=draft_schedule,
            title="T",
            start_time="10:00",
            end_time="11:00",
            category="work",
        )
        draft_schedule.status = Schedule.Status.DRAFT
        draft_schedule.save(update_fields=["status"])

        resp = auth_client.delete(f"/api/blocks/{block.id}/")
        assert resp.status_code == 200
        draft_schedule.refresh_from_db()
        assert draft_schedule.status == Schedule.Status.ACTIVE

    def test_reorder_flips(self, auth_client, draft_schedule):
        b1 = TimeBlock.objects.create(
            schedule=draft_schedule,
            title="A",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        b2 = TimeBlock.objects.create(
            schedule=draft_schedule,
            title="B",
            start_time="10:00",
            end_time="11:00",
            category="work",
        )
        draft_schedule.status = Schedule.Status.DRAFT
        draft_schedule.save(update_fields=["status"])

        resp = auth_client.post(
            "/api/blocks/reorder/",
            json.dumps(
                {
                    "updates": [
                        {
                            "id": b1.id,
                            "start_time": "09:00",
                            "end_time": "10:00",
                            "sort_order": 1,
                        },
                        {
                            "id": b2.id,
                            "start_time": "10:00",
                            "end_time": "11:00",
                            "sort_order": 0,
                        },
                    ]
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        draft_schedule.refresh_from_db()
        assert draft_schedule.status == Schedule.Status.ACTIVE


@pytest.mark.django_db
class TestRestoreDoesNotFlip:
    def test_draft_stays_draft_on_empty_restore(
        self, auth_client, draft_schedule
    ):
        resp = auth_client.post(
            "/api/schedules/2026-05-04/blocks/restore/",
            json.dumps({"blocks": []}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        draft_schedule.refresh_from_db()
        assert draft_schedule.status == Schedule.Status.DRAFT

    def test_active_stays_active_on_restore(self, auth_client, user):
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 4),
            status=Schedule.Status.ACTIVE,
        )
        resp = auth_client.post(
            "/api/schedules/2026-05-04/blocks/restore/",
            json.dumps({"blocks": []}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        s.refresh_from_db()
        assert s.status == Schedule.Status.ACTIVE
