"""Tests for the ``Schedule.status`` flip rules.

The badge contract: every forward-mutating endpoint flips ``draft →
active`` on its first run (and ``reviewed → active`` on any edit to a
reviewed day, post-Phase 6); ``restore_blocks`` (the undo target)
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
class TestMarkActiveOnEdit:
    def test_flips_draft_to_active(self, draft_schedule):
        flipped = draft_schedule.mark_active_on_edit()
        assert flipped is True
        # In-memory copy is synced after a successful UPDATE so callers
        # that re-read ``self.status`` see the new value without a refetch.
        assert draft_schedule.status == Schedule.Status.ACTIVE
        draft_schedule.refresh_from_db()
        assert draft_schedule.status == Schedule.Status.ACTIVE

    def test_flips_reviewed_to_active(self, user):
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 6),
            status=Schedule.Status.REVIEWED,
        )
        flipped = s.mark_active_on_edit()
        assert flipped is True
        assert s.status == Schedule.Status.ACTIVE
        s.refresh_from_db()
        assert s.status == Schedule.Status.ACTIVE

    def test_no_op_when_active(self, user):
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 5),
            status=Schedule.Status.ACTIVE,
        )
        flipped = s.mark_active_on_edit()
        assert flipped is False
        s.refresh_from_db()
        assert s.status == Schedule.Status.ACTIVE

    def test_stale_instance_recovery(self, user):
        """Regression test for the conditional-UPDATE pattern.

        Loads a Schedule with ``status=ACTIVE`` into an instance ``s``,
        then bypasses the in-memory copy by updating the row directly to
        ``REVIEWED`` (simulates a concurrent ``mark_reviewed`` committing
        in another transaction). Calling ``s.mark_active_on_edit()`` on
        the stale instance must still flip the row back to ACTIVE, even
        though the Python-side ``s.status`` still says ACTIVE.

        Without the conditional UPDATE pattern this test fails: a
        Python-side ``self.status`` check would short-circuit the flip,
        leaving the DB row frozen-reviewed with a stale snapshot.
        """
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 7),
            status=Schedule.Status.ACTIVE,
        )
        # Bypass the in-memory copy.
        Schedule.objects.filter(pk=s.pk).update(
            status=Schedule.Status.REVIEWED
        )
        # ``s.status`` is still ACTIVE in memory — a Python-side check
        # would (incorrectly) treat this as a no-op.
        assert s.status == Schedule.Status.ACTIVE

        flipped = s.mark_active_on_edit()
        assert flipped is True
        assert s.status == Schedule.Status.ACTIVE  # in-memory synced
        # DB-state half of the regression — without ``assert`` this line
        # would silently degrade to a no-op expression and let a future
        # refactor that drops the conditional UPDATE pass the test.
        assert Schedule.objects.get(pk=s.pk).status == Schedule.Status.ACTIVE


@pytest.mark.django_db
class TestMarkReviewedIfActive:
    def test_flips_active_to_reviewed(self, user):
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 8),
            status=Schedule.Status.ACTIVE,
        )
        flipped = s.mark_reviewed_if_active()
        assert flipped is True
        # Symmetric in-memory sync (mirrors mark_active_on_edit).
        assert s.status == Schedule.Status.REVIEWED
        s.refresh_from_db()
        assert s.status == Schedule.Status.REVIEWED

    def test_no_op_when_reviewed(self, user):
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 9),
            status=Schedule.Status.REVIEWED,
        )
        flipped = s.mark_reviewed_if_active()
        assert flipped is False
        s.refresh_from_db()
        assert s.status == Schedule.Status.REVIEWED

    def test_refuses_on_draft(self, user):
        """A never-edited day cannot be reviewed — analytics would be
        meaningless on auto-draft data the user never touched."""
        s = Schedule.objects.create(
            user=user,
            date=datetime.date(2026, 5, 10),
            status=Schedule.Status.DRAFT,
        )
        flipped = s.mark_reviewed_if_active()
        assert flipped is False
        s.refresh_from_db()
        assert s.status == Schedule.Status.DRAFT


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

    def test_create_block_from_event_flips(self, auth_client, draft_schedule):
        resp = auth_client.post(
            "/api/schedules/2026-05-04/blocks/from-event/",
            json.dumps(
                {
                    "title": "Dentist",
                    "start_time": "14:07",
                    "end_time": "14:33",
                    "category": "other",
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


@pytest.fixture
def reviewed_schedule(user):
    return Schedule.objects.create(
        user=user, date=datetime.date(2026, 5, 4), status=Schedule.Status.REVIEWED
    )


@pytest.mark.django_db
class TestReviewedUnfreezesOnEdit:
    """Editing any block on a ``reviewed`` schedule flips status back to
    ``active`` so the next analytics visit recomputes (frozen-vs-recompute
    rule). Covers every forward-mutating endpoint.
    """

    def test_create_block_flips_reviewed_to_active(
        self, auth_client, reviewed_schedule
    ):
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
        reviewed_schedule.refresh_from_db()
        assert reviewed_schedule.status == Schedule.Status.ACTIVE

    def test_create_block_from_event_flips_reviewed_to_active(
        self, auth_client, reviewed_schedule
    ):
        resp = auth_client.post(
            "/api/schedules/2026-05-04/blocks/from-event/",
            json.dumps(
                {
                    "title": "Dentist",
                    "start_time": "14:07",
                    "end_time": "14:33",
                    "category": "other",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201
        reviewed_schedule.refresh_from_db()
        assert reviewed_schedule.status == Schedule.Status.ACTIVE

    def test_patch_block_flips_reviewed_to_active(
        self, auth_client, reviewed_schedule
    ):
        block = TimeBlock.objects.create(
            schedule=reviewed_schedule,
            title="T",
            start_time="10:00",
            end_time="11:00",
            category="work",
        )
        # Restore to REVIEWED in case the create above flipped it.
        Schedule.objects.filter(pk=reviewed_schedule.pk).update(
            status=Schedule.Status.REVIEWED
        )
        resp = auth_client.patch(
            f"/api/blocks/{block.id}/",
            json.dumps({"title": "Renamed"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        reviewed_schedule.refresh_from_db()
        assert reviewed_schedule.status == Schedule.Status.ACTIVE

    def test_delete_block_flips_reviewed_to_active(
        self, auth_client, reviewed_schedule
    ):
        block = TimeBlock.objects.create(
            schedule=reviewed_schedule,
            title="T",
            start_time="10:00",
            end_time="11:00",
            category="work",
        )
        Schedule.objects.filter(pk=reviewed_schedule.pk).update(
            status=Schedule.Status.REVIEWED
        )
        resp = auth_client.delete(f"/api/blocks/{block.id}/")
        assert resp.status_code == 200
        reviewed_schedule.refresh_from_db()
        assert reviewed_schedule.status == Schedule.Status.ACTIVE

    def test_reorder_flips_reviewed_to_active(
        self, auth_client, reviewed_schedule
    ):
        b1 = TimeBlock.objects.create(
            schedule=reviewed_schedule,
            title="A",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        b2 = TimeBlock.objects.create(
            schedule=reviewed_schedule,
            title="B",
            start_time="10:00",
            end_time="11:00",
            category="work",
        )
        Schedule.objects.filter(pk=reviewed_schedule.pk).update(
            status=Schedule.Status.REVIEWED
        )
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
        reviewed_schedule.refresh_from_db()
        assert reviewed_schedule.status == Schedule.Status.ACTIVE
