"""Tests for the analytics endpoints.

Covers ``analytics_view`` (Inertia render), ``mark_reviewed`` (the
hard-idempotent POST), and ``update_review_notes`` (PATCH). The
non-obvious cases here are the idempotency / race rules — see the
inline comments before each test for what they pin.
"""
import datetime
import json

import pytest
from analytics.models import DailyReview
from analytics.services import recompute_review_from_schedule
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from schedules.models import Schedule, TimeBlock

ANALYTICS_URL = "/analytics/{date}/"
MARK_REVIEWED_URL = "/api/analytics/schedules/{date}/mark-reviewed/"
NOTES_URL = "/api/analytics/reviews/{pk}/notes/"


def _make_block(schedule, start, end, *, completed=False, category="work"):
    return TimeBlock.objects.create(
        schedule=schedule,
        title="t",
        start_time=start,
        end_time=end,
        category=category,
        is_completed=completed,
    )


def _props(resp):
    return json.loads(resp.content)["props"]


@pytest.fixture
def auth_inertia_client(auth_client):
    auth_client.defaults["HTTP_X_INERTIA"] = "true"
    return auth_client


@pytest.fixture
def past_date():
    return datetime.date(2026, 4, 1)


@pytest.fixture
def active_schedule(user, past_date):
    s = Schedule.objects.create(
        user=user, date=past_date, status=Schedule.Status.ACTIVE
    )
    _make_block(s, "09:00", "10:00", completed=True)
    _make_block(s, "10:00", "11:00", completed=False)
    return s


@pytest.fixture
def reviewed_schedule(user, past_date):
    s = Schedule.objects.create(
        user=user, date=past_date, status=Schedule.Status.REVIEWED
    )
    _make_block(s, "09:00", "10:00", completed=True)
    _make_block(s, "10:00", "11:00", completed=False)
    DailyReview.objects.create(
        schedule=s,
        planned_count=2,
        completed_count=1,
        skipped_count=1,
        notes="frozen notes",
    )
    return s


@pytest.mark.django_db
class TestAnalyticsView:
    def test_404_on_missing_schedule(self, auth_inertia_client, past_date):
        resp = auth_inertia_client.get(ANALYTICS_URL.format(date=past_date))
        assert resp.status_code == 404

    def test_400_on_future_date(self, auth_inertia_client):
        future = (
            timezone.localdate() + datetime.timedelta(days=30)
        ).isoformat()
        resp = auth_inertia_client.get(ANALYTICS_URL.format(date=future))
        assert resp.status_code == 400

    def test_400_on_invalid_date_format(self, auth_inertia_client):
        resp = auth_inertia_client.get(ANALYTICS_URL.format(date="not-a-date"))
        assert resp.status_code == 400

    def test_recomputes_on_active_schedule(
        self, auth_inertia_client, active_schedule, past_date
    ):
        """Each visit while ACTIVE refreshes the snapshot — ``updated_at``
        must strictly advance between two visits (pins the "fresh while
        active" rule)."""
        resp1 = auth_inertia_client.get(ANALYTICS_URL.format(date=past_date))
        assert resp1.status_code == 200
        first_updated_at = _props(resp1)["review"]["updated_at"]

        # Toggle a block so the recompute has something to capture.
        block = active_schedule.time_blocks.get(start_time="10:00")
        block.is_completed = True
        block.save()

        resp2 = auth_inertia_client.get(ANALYTICS_URL.format(date=past_date))
        review = _props(resp2)["review"]
        assert review["updated_at"] > first_updated_at
        assert review["completed_count"] == 2

    def test_frozen_on_reviewed_schedule(
        self, auth_inertia_client, reviewed_schedule, past_date
    ):
        """A ``REVIEWED`` schedule serves the frozen snapshot — even if
        blocks have changed since (which shouldn't happen via the API
        but we still pin the contract)."""
        resp1 = auth_inertia_client.get(ANALYTICS_URL.format(date=past_date))
        first_updated_at = _props(resp1)["review"]["updated_at"]
        resp2 = auth_inertia_client.get(ANALYTICS_URL.format(date=past_date))
        assert _props(resp2)["review"]["updated_at"] == first_updated_at
        assert _props(resp2)["review"]["notes"] == "frozen notes"

    def test_back_compat_recomputes_reviewed_without_row(
        self, auth_inertia_client, user, past_date
    ):
        """A ``reviewed`` schedule predating Phase 6 has no DailyReview;
        the view should recompute once and serve."""
        s = Schedule.objects.create(
            user=user, date=past_date, status=Schedule.Status.REVIEWED
        )
        _make_block(s, "09:00", "10:00", completed=True)
        assert not DailyReview.objects.filter(schedule=s).exists()
        resp = auth_inertia_client.get(ANALYTICS_URL.format(date=past_date))
        assert resp.status_code == 200
        assert DailyReview.objects.filter(schedule=s).exists()

    def test_forwards_blocks_for_skipped_panel(
        self, auth_inertia_client, active_schedule, past_date
    ):
        resp = auth_inertia_client.get(ANALYTICS_URL.format(date=past_date))
        props = _props(resp)
        assert len(props["blocks"]) == 2
        assert {"id", "title", "start_time", "end_time", "category"}.issubset(
            props["blocks"][0]
        )

    def test_includes_streak_payload(
        self, auth_inertia_client, active_schedule, past_date
    ):
        resp = auth_inertia_client.get(ANALYTICS_URL.format(date=past_date))
        streak = _props(resp)["streak"]
        assert "current" in streak
        assert "threshold" in streak
        assert "window_days" in streak


@pytest.mark.django_db
class TestMarkReviewed:
    def test_400_on_draft_schedule(self, auth_client, user, past_date):
        Schedule.objects.create(
            user=user, date=past_date, status=Schedule.Status.DRAFT
        )
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date), "", content_type="application/json"
        )
        assert resp.status_code == 400
        assert not DailyReview.objects.exists()

    def test_active_to_reviewed_persists_and_flips(
        self, auth_client, active_schedule, past_date
    ):
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            "",
            content_type="application/json",
        )
        assert resp.status_code == 200
        active_schedule.refresh_from_db()
        assert active_schedule.status == Schedule.Status.REVIEWED
        review = DailyReview.objects.get(schedule=active_schedule)
        assert review.planned_count == 2
        assert review.completed_count == 1

    def test_idempotent_returns_same_snapshot_unchanged_updated_at(
        self, auth_client, active_schedule, past_date
    ):
        """Two calls on the same schedule: the first flips and writes;
        the second returns the persisted snapshot WITHOUT recomputing.
        ``updated_at`` must be identical between the two responses."""
        resp1 = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            "",
            content_type="application/json",
        )
        first = json.loads(resp1.content)
        resp2 = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            "",
            content_type="application/json",
        )
        second = json.loads(resp2.content)
        assert first["updated_at"] == second["updated_at"]

    def test_idempotent_ignores_different_notes_on_reviewed(
        self, auth_client, reviewed_schedule, past_date
    ):
        """A second call with ``{"notes": "different"}`` returns the
        snapshot — notes in DB must NOT change. Pins the "POST body
        ignored on REVIEWED" rule."""
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            json.dumps({"notes": "different"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        review = DailyReview.objects.get(schedule=reviewed_schedule)
        assert review.notes == "frozen notes"

    def test_idempotent_tolerates_malformed_body_on_reviewed(
        self, auth_client, reviewed_schedule, past_date
    ):
        """A retry with corrupted JSON to a REVIEWED schedule returns
        200 with the snapshot, NOT 400. Pins the "body parsed only
        after under-lock status check" ordering — without it, a flaky
        network's second attempt would surface as a 400 even though the
        first succeeded."""
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            "{not json",
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = json.loads(resp.content)
        assert body["notes"] == "frozen notes"

    def test_optional_notes_persisted_on_active_to_reviewed(
        self, auth_client, active_schedule, past_date
    ):
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            json.dumps({"notes": "Felt focused"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        review = DailyReview.objects.get(schedule=active_schedule)
        assert review.notes == "Felt focused"

    def test_empty_body_accepted_on_active(
        self, auth_client, active_schedule, past_date
    ):
        """A bare ``fetch(url, { method: 'POST' })`` shouldn't 400 on
        the parser before the validator can decide whether the body is
        needed at all."""
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            "",
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_invalid_json_on_active_path_400s(
        self, auth_client, active_schedule, past_date
    ):
        """The parser is reached on the ACTIVE path under the lock —
        malformed JSON is a real error there."""
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            "{not json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_oversized_body_returns_413(
        self, auth_client, active_schedule, past_date
    ):
        big = "x" * 200_000
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            json.dumps({"notes": big}),
            content_type="application/json",
        )
        assert resp.status_code == 413

    def test_locks_parent_schedule_row(
        self, auth_client, active_schedule, past_date, monkeypatch
    ):
        """Mirror of ``ai_views_draft.TestApplyLocksScheduleRow``: the
        active→reviewed path must call
        ``Schedule.objects.select_for_update`` so concurrent edits queue
        up behind us under PostgreSQL. SQLite ignores the lock silently;
        we spy the call to verify intent."""
        original = Schedule.objects.select_for_update
        called = {"v": False}

        def _spy(*args, **kwargs):
            called["v"] = True
            return original(*args, **kwargs)

        monkeypatch.setattr(
            Schedule.objects, "select_for_update", _spy, raising=True
        )
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            "",
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert called["v"]

    def test_ignores_extra_fields(
        self, auth_client, active_schedule, past_date
    ):
        """Project-wide convention: unknown fields are silently dropped
        (no strict mode anywhere). ``evil_status`` and ``schedule_id``
        must not influence the result."""
        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            json.dumps(
                {
                    "notes": "ok",
                    "evil_status": "draft",
                    "schedule_id": 99999,
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        active_schedule.refresh_from_db()
        assert active_schedule.status == Schedule.Status.REVIEWED
        review = DailyReview.objects.get(schedule=active_schedule)
        assert review.notes == "ok"

    def test_under_lock_recheck_skips_recompute_when_already_reviewed(
        self, auth_client, active_schedule, past_date, monkeypatch
    ):
        """Simulate a concurrent commit between the pre-lock check and
        the lock acquisition: the under-lock SELECT returns a REVIEWED
        schedule. The view must serve the snapshot without calling
        ``recompute_review_from_schedule``. Pins the double-checked
        locking pattern."""
        # Pre-create the snapshot (mark_reviewed_if_active is what
        # would normally write it; we emulate the just-committed state).
        recompute_review_from_schedule(active_schedule)

        # Have the under-lock GET return a copy with status REVIEWED so
        # the recheck branch fires. We patch the QuerySet returned by
        # ``select_for_update().prefetch_related(...)`` so its ``get``
        # yields our doctored schedule.
        from analytics import views as analytics_views

        recompute_calls = {"n": 0}
        original_recompute = analytics_views.recompute_review_from_schedule

        def _counting_recompute(*args, **kwargs):
            recompute_calls["n"] += 1
            return original_recompute(*args, **kwargs)

        monkeypatch.setattr(
            analytics_views,
            "recompute_review_from_schedule",
            _counting_recompute,
        )

        # Build the doctored schedule.
        doctored = Schedule.objects.get(pk=active_schedule.pk)
        doctored.status = Schedule.Status.REVIEWED

        def _patched_sfu(*args, **kwargs):
            # Intentionally bypass the real queryset chain — we only
            # need ``.prefetch_related().get()`` to return our doctored
            # schedule, simulating a concurrent commit between the
            # pre-lock check and the lock acquisition.
            class _Wrapper:
                def prefetch_related(self, *a, **k):
                    return self

                def get(self_inner, **kwargs):  # noqa: N805
                    return doctored

            return _Wrapper()

        monkeypatch.setattr(
            Schedule.objects, "select_for_update", _patched_sfu, raising=True
        )

        resp = auth_client.post(
            MARK_REVIEWED_URL.format(date=past_date),
            "",
            content_type="application/json",
        )
        assert resp.status_code == 200
        # The under-lock branch is the REVIEWED idempotent path — it
        # MUST NOT recompute (only the pre-test setup call counts).
        # That setup call ran BEFORE we installed the monkeypatch, so
        # ``recompute_calls["n"]`` should be exactly 0.
        assert recompute_calls["n"] == 0


@pytest.mark.django_db
class TestUpdateReviewNotes:
    @pytest.fixture
    def review(self, active_schedule):
        return recompute_review_from_schedule(active_schedule)

    def test_updates_notes(self, auth_client, review):
        resp = auth_client.patch(
            NOTES_URL.format(pk=review.id),
            json.dumps({"notes": "new notes"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        review.refresh_from_db()
        assert review.notes == "new notes"

    def test_cross_user_404(self, review):
        other_user = User.objects.create_user(
            username="other", password="pw"
        )
        client = Client()
        client.login(username="other", password="pw")
        resp = client.patch(
            NOTES_URL.format(pk=review.id),
            json.dumps({"notes": "hax"}),
            content_type="application/json",
        )
        assert resp.status_code == 404
        review.refresh_from_db()
        assert review.notes != "hax"
        # Cleanup
        other_user.delete()

    def test_notes_too_long_400(self, auth_client, review):
        resp = auth_client.patch(
            NOTES_URL.format(pk=review.id),
            json.dumps({"notes": "x" * 2001}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_invalid_json_400(self, auth_client, review):
        resp = auth_client.patch(
            NOTES_URL.format(pk=review.id),
            "{not json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_empty_body_400(self, auth_client, review):
        """PATCH with no field to update is degenerate — the empty-body
        convention is for POSTs that can be valid no-ops, not PATCH."""
        resp = auth_client.patch(
            NOTES_URL.format(pk=review.id),
            "",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_oversized_body_413(self, auth_client, review):
        # Use a string longer than the 100KB cap.
        resp = auth_client.patch(
            NOTES_URL.format(pk=review.id),
            json.dumps({"notes": "x" * 200_000}),
            content_type="application/json",
        )
        assert resp.status_code == 413

    def test_other_fields_ignored(self, auth_client, review):
        resp = auth_client.patch(
            NOTES_URL.format(pk=review.id),
            json.dumps(
                {
                    "notes": "ok",
                    "completed_count": 999,
                    "schedule_id": 1,
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        review.refresh_from_db()
        assert review.notes == "ok"
        assert review.completed_count != 999
