"""Feature 0026 — from-event block create, off-grid lifecycle, travel rules.

Covers:

* ``create_block_from_event`` — the single sanctioned off-grid create path
  (no 5-minute granularity), everything else matching ``create_block``.
* Off-grid block lifecycle — non-time PATCHes must not re-fail the field
  validators (would have caught the ``block_detail`` regression).
* AI move/resize on off-grid blocks — action-supplied-only granularity /
  day-window checks; bare-move duration round-up.
* ``TravelRule`` CRUD — validation, ordering, per-user isolation, cap.
"""
import json

import pytest
from ai.service import AICommandResult
from calendar_sync.models import TravelRule
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock

FROM_EVENT_URL = "/api/schedules/2026-04-07/blocks/from-event/"
RULES_URL = "/api/calendar/travel-rules/"


def _post_from_event(client, body, url=FROM_EVENT_URL):
    return client.post(url, json.dumps(body), content_type="application/json")


def _valid_body(**overrides):
    body = {
        "title": "Dentist",
        "start_time": "14:07",
        "end_time": "14:33",
        "category": "other",
    }
    body.update(overrides)
    return body


@pytest.fixture
def off_grid_block(schedule):
    return TimeBlock.objects.create(
        schedule=schedule,
        title="Dentist",
        start_time="14:07",
        end_time="14:33",
        category="other",
    )


class TestCreateBlockFromEvent:
    @pytest.mark.django_db
    def test_off_grid_times_accepted(self, auth_client, schedule):
        resp = _post_from_event(auth_client, _valid_body())
        assert resp.status_code == 201
        data = resp.json()
        assert data["start_time"] == "14:07"
        assert data["end_time"] == "14:33"
        assert data["category"] == "other"
        block = TimeBlock.objects.get(pk=data["id"])
        assert block.schedule == schedule

    @pytest.mark.django_db
    def test_category_defaults_to_other(self, auth_client, schedule):
        body = _valid_body()
        del body["category"]
        resp = _post_from_event(auth_client, body)
        assert resp.status_code == 201
        assert resp.json()["category"] == "other"

    @pytest.mark.django_db
    def test_clamp_boundary_times_accepted(self, auth_client, schedule):
        resp = _post_from_event(
            auth_client, _valid_body(start_time="00:00", end_time="23:59")
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["start_time"] == "00:00"
        assert data["end_time"] == "23:59"

    @pytest.mark.django_db
    def test_creates_schedule_when_missing(self, auth_client, user):
        assert not Schedule.objects.filter(user=user, date="2026-04-07").exists()
        resp = _post_from_event(auth_client, _valid_body())
        assert resp.status_code == 201
        assert Schedule.objects.filter(user=user, date="2026-04-07").exists()

    @pytest.mark.django_db
    def test_overlap_rejected_with_manual_create_error(
        self, auth_client, schedule, off_grid_block
    ):
        resp = _post_from_event(
            auth_client, _valid_body(start_time="14:20", end_time="15:00")
        )
        assert resp.status_code == 400
        assert resp.json()["errors"]["time"] == (
            "This block overlaps with an existing block."
        )
        # Schedule unchanged — only the pre-existing block remains.
        assert TimeBlock.objects.filter(schedule=schedule).count() == 1

    @pytest.mark.django_db
    def test_readd_same_event_allowed(self, auth_client, schedule):
        """Re-adding is always allowed (no dedupe) — as long as the slot
        is free."""
        assert _post_from_event(auth_client, _valid_body()).status_code == 201
        resp = _post_from_event(
            auth_client, _valid_body(start_time="16:07", end_time="16:33")
        )
        assert resp.status_code == 201
        assert TimeBlock.objects.filter(
            schedule=schedule, title="Dentist"
        ).count() == 2

    @pytest.mark.django_db
    def test_start_not_before_end_rejected(self, auth_client, schedule):
        resp = _post_from_event(
            auth_client, _valid_body(start_time="14:33", end_time="14:33")
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_invalid_time_format_rejected(self, auth_client, schedule):
        resp = _post_from_event(auth_client, _valid_body(start_time="2 pm"))
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_missing_times_rejected(self, auth_client, schedule):
        body = _valid_body()
        del body["end_time"]
        resp = _post_from_event(auth_client, body)
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_empty_title_rejected(self, auth_client, schedule):
        resp = _post_from_event(auth_client, _valid_body(title="   "))
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_title_too_long_rejected(self, auth_client, schedule):
        resp = _post_from_event(auth_client, _valid_body(title="x" * 256))
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_invalid_category_rejected(self, auth_client, schedule):
        resp = _post_from_event(auth_client, _valid_body(category="commute"))
        assert resp.status_code == 400

    @pytest.mark.django_db
    @pytest.mark.parametrize("raw_body", ["[]", '"x"', "123", "null", "true"])
    def test_non_dict_json_body_rejected(self, auth_client, schedule, raw_body):
        resp = auth_client.post(
            FROM_EVENT_URL, raw_body, content_type="application/json"
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "field,value",
        [
            ("title", 42),
            ("category", ["work"]),
            ("start_time", 1407),
            ("end_time", None),
        ],
    )
    def test_non_string_fields_rejected(self, auth_client, schedule, field, value):
        """``create_block`` would 500 on these; the from-event endpoint
        must return a structured 400 instead."""
        resp = _post_from_event(auth_client, _valid_body(**{field: value}))
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_invalid_json_rejected(self, auth_client, schedule):
        resp = auth_client.post(
            FROM_EVENT_URL, "{", content_type="application/json"
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_invalid_date_rejected(self, auth_client):
        resp = _post_from_event(
            auth_client,
            _valid_body(),
            url="/api/schedules/not-a-date/blocks/from-event/",
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_oversized_body_rejected(self, auth_client, schedule):
        resp = _post_from_event(auth_client, _valid_body(title="x" * 200_000))
        assert resp.status_code == 413

    @pytest.mark.django_db
    def test_unauthenticated_redirects(self, client):
        resp = _post_from_event(client, _valid_body())
        assert resp.status_code == 302

    @pytest.mark.django_db
    def test_csrf_enforced(self, csrf_auth_client, schedule):
        resp = _post_from_event(csrf_auth_client, _valid_body())
        assert resp.status_code == 403


class TestOffGridBlockLifecycle:
    """Would have caught the ``block_detail`` unconditional-full_clean
    regression: non-time PATCHes on an off-grid block must not 400."""

    @pytest.mark.django_db
    def test_completion_toggle_succeeds(self, auth_client, off_grid_block):
        resp = auth_client.patch(
            f"/api/blocks/{off_grid_block.id}/",
            json.dumps({"is_completed": True}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        off_grid_block.refresh_from_db()
        assert off_grid_block.is_completed is True
        # Times untouched.
        assert off_grid_block.start_time.strftime("%H:%M") == "14:07"

    @pytest.mark.django_db
    def test_title_edit_succeeds(self, auth_client, off_grid_block):
        resp = auth_client.patch(
            f"/api/blocks/{off_grid_block.id}/",
            json.dumps({"title": "Dentist (moved)"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        off_grid_block.refresh_from_db()
        assert off_grid_block.title == "Dentist (moved)"

    @pytest.mark.django_db
    def test_manual_time_edit_still_enforces_granularity(
        self, auth_client, off_grid_block
    ):
        resp = auth_client.patch(
            f"/api/blocks/{off_grid_block.id}/",
            json.dumps({"start_time": "15:02", "end_time": "15:28"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_partial_end_patch_keeps_off_grid_start(
        self, auth_client, off_grid_block
    ):
        """PATCH only end_time must not re-validate the inherited off-grid start."""
        resp = auth_client.patch(
            f"/api/blocks/{off_grid_block.id}/",
            json.dumps({"end_time": "15:00"}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        off_grid_block.refresh_from_db()
        assert off_grid_block.start_time.strftime("%H:%M") == "14:07"
        assert off_grid_block.end_time.strftime("%H:%M") == "15:00"

    @pytest.mark.django_db
    def test_partial_end_patch_rejects_off_grid_end(
        self, auth_client, off_grid_block
    ):
        resp = auth_client.patch(
            f"/api/blocks/{off_grid_block.id}/",
            json.dumps({"end_time": "15:03"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_resubmitting_unchanged_off_grid_times_succeeds(
        self, auth_client, off_grid_block
    ):
        """Echoing back the stored off-grid times must not 400.

        ``reorder_blocks`` validates only *changed* times; ``block_detail``
        does the same, so a client that PATCHes the whole block (times
        included) while editing only the title stays working.
        """
        resp = auth_client.patch(
            f"/api/blocks/{off_grid_block.id}/",
            json.dumps(
                {
                    "title": "Dentist (same times)",
                    "start_time": "14:07",
                    "end_time": "14:33",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        off_grid_block.refresh_from_db()
        assert off_grid_block.title == "Dentist (same times)"
        assert off_grid_block.start_time.strftime("%H:%M") == "14:07"
        assert off_grid_block.end_time.strftime("%H:%M") == "14:33"

    @pytest.mark.django_db
    def test_changing_one_time_to_off_grid_still_rejected(
        self, auth_client, off_grid_block
    ):
        """The unchanged-time skip must not become a blanket bypass.

        Start is echoed back unchanged (legal); end moves to a *new* off-grid
        value and must still 400.
        """
        resp = auth_client.patch(
            f"/api/blocks/{off_grid_block.id}/",
            json.dumps({"start_time": "14:07", "end_time": "14:41"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        off_grid_block.refresh_from_db()
        assert off_grid_block.end_time.strftime("%H:%M") == "14:33"

    @pytest.mark.django_db
    def test_on_grid_time_pair_replace_succeeds(
        self, auth_client, off_grid_block
    ):
        resp = auth_client.patch(
            f"/api/blocks/{off_grid_block.id}/",
            json.dumps({"start_time": "15:00", "end_time": "15:30"}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        off_grid_block.refresh_from_db()
        assert off_grid_block.start_time.strftime("%H:%M") == "15:00"
        assert off_grid_block.end_time.strftime("%H:%M") == "15:30"

    @pytest.mark.django_db
    def test_delete_succeeds(self, auth_client, off_grid_block):
        resp = auth_client.delete(f"/api/blocks/{off_grid_block.id}/")
        assert resp.status_code == 200
        assert not TimeBlock.objects.filter(pk=off_grid_block.id).exists()


class TestAIMoveResizeOffGrid:
    """Action-supplied-only granularity/day-window: inherited off-grid or
    clamp-to-day times must not fail AI move/resize; the AI still cannot
    introduce *new* off-grid times."""

    URL = "/api/ai/schedules/2026-04-18/command/"

    @pytest.fixture
    def ai_schedule(self, user):
        return Schedule.objects.create(user=user, date="2026-04-18")

    def _patch_run(self, monkeypatch, actions):
        async def _run(*args, **kwargs):
            return AICommandResult(
                raw_response_text="{}",
                parsed_actions=actions,
                explanation="ok",
            )

        monkeypatch.setattr("ai.views.run_command", _run)

    def _post(self, client, command="do it"):
        return client.post(
            self.URL, json.dumps({"command": command}),
            content_type="application/json",
        )

    @pytest.mark.django_db
    def test_bare_move_rounds_off_grid_duration_up(
        self, auth_client, ai_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=ai_schedule, title="Dentist",
            start_time="14:07", end_time="14:33", category="other",
        )
        self._patch_run(
            monkeypatch,
            [{"type": "move", "task_id": block.id, "start_time": "16:00"}],
        )
        resp = self._post(auth_client)
        assert resp.status_code == 200
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "16:00"
        # 26-minute duration rounded UP to 30 (normalize-on-move).
        assert block.end_time.strftime("%H:%M") == "16:30"

    @pytest.mark.django_db
    def test_resize_inherits_off_grid_start(
        self, auth_client, ai_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=ai_schedule, title="Dentist",
            start_time="14:07", end_time="14:33", category="other",
        )
        self._patch_run(
            monkeypatch,
            [{"type": "resize", "task_id": block.id, "end_time": "15:00"}],
        )
        resp = self._post(auth_client)
        assert resp.status_code == 200
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "14:07"  # inherited
        assert block.end_time.strftime("%H:%M") == "15:00"

    @pytest.mark.django_db
    def test_resize_inherits_clamp_to_day_start(
        self, auth_client, ai_schedule, monkeypatch
    ):
        """A clamp-to-day from-event block (00:00 start, outside the
        06:00–23:00 window) must stay resizable on its inherited start."""
        block = TimeBlock.objects.create(
            schedule=ai_schedule, title="Red-eye",
            start_time="00:00", end_time="06:30", category="other",
        )
        self._patch_run(
            monkeypatch,
            [{"type": "resize", "task_id": block.id, "end_time": "07:00"}],
        )
        resp = self._post(auth_client)
        assert resp.status_code == 200
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "00:00"
        assert block.end_time.strftime("%H:%M") == "07:00"

    @pytest.mark.django_db
    def test_action_supplied_off_grid_time_still_rejected(
        self, auth_client, ai_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=ai_schedule, title="Gym",
            start_time="17:00", end_time="18:00", category="health",
        )
        self._patch_run(
            monkeypatch,
            [{"type": "move", "task_id": block.id, "start_time": "17:03"}],
        )
        resp = self._post(auth_client)
        assert resp.status_code == 400
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "17:00"


class TestTravelRuleCrud:
    def _create(self, client, **fields):
        body = {"keyword": "dentist", **fields}
        return client.post(
            RULES_URL, json.dumps(body), content_type="application/json"
        )

    @pytest.mark.django_db
    def test_create_and_list_ordering(self, auth_client, user):
        assert self._create(auth_client, keyword="dentist").status_code == 201
        assert self._create(auth_client, keyword="gym").status_code == 201
        assert self._create(auth_client, keyword="office", order=-5).status_code == 201
        resp = auth_client.get(RULES_URL)
        assert resp.status_code == 200
        rules = resp.json()["travel_rules"]
        # Explicit order=-5 sorts first; omitted orders are born distinct
        # ascending (max+1) so creation order is preserved.
        assert [r["keyword"] for r in rules] == ["office", "dentist", "gym"]

    @pytest.mark.django_db
    def test_omitted_order_assigned_max_plus_one(self, auth_client, user):
        first = self._create(auth_client, keyword="a").json()
        second = self._create(auth_client, keyword="b").json()
        assert second["order"] == first["order"] + 1

    @pytest.mark.django_db
    def test_create_defaults(self, auth_client, user):
        data = self._create(auth_client).json()
        assert data["travel_there_minutes"] == 0
        assert data["travel_back_minutes"] == 0
        assert data["category"] == ""

    @pytest.mark.django_db
    def test_create_full_payload(self, auth_client, user):
        resp = self._create(
            auth_client,
            travel_there_minutes=30,
            travel_back_minutes=45,
            category="health",
            order=3,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["travel_there_minutes"] == 30
        assert data["travel_back_minutes"] == 45
        assert data["category"] == "health"
        assert data["order"] == 3

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "field,value",
        [
            ("keyword", ""),
            ("keyword", "   "),
            ("keyword", 42),
            ("keyword", "x" * 101),
            ("travel_there_minutes", -1),
            ("travel_there_minutes", 601),
            ("travel_there_minutes", True),
            ("travel_there_minutes", "30"),
            ("travel_back_minutes", 1000),
            ("category", "commute"),
            ("category", ["work"]),
            ("order", "first"),
            ("order", 2_000_000),
        ],
    )
    def test_create_validation_rejected(self, auth_client, user, field, value):
        resp = self._create(auth_client, **{field: value})
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_patch_updates_fields(self, auth_client, user):
        rule_id = self._create(auth_client).json()["id"]
        resp = auth_client.patch(
            f"{RULES_URL}{rule_id}/",
            json.dumps({"travel_there_minutes": 20, "category": "work"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["travel_there_minutes"] == 20
        assert data["category"] == "work"

    @pytest.mark.django_db
    def test_patch_empty_body_rejected(self, auth_client, user):
        rule_id = self._create(auth_client).json()["id"]
        resp = auth_client.patch(
            f"{RULES_URL}{rule_id}/",
            json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_delete(self, auth_client, user):
        rule_id = self._create(auth_client).json()["id"]
        resp = auth_client.delete(f"{RULES_URL}{rule_id}/")
        assert resp.status_code == 200
        assert not TravelRule.objects.filter(pk=rule_id).exists()

    @pytest.mark.django_db
    def test_cross_user_pk_returns_404(self, auth_client, db):
        other = User.objects.create_user(username="other", password="pass123")
        rule = TravelRule.objects.create(user=other, keyword="secret")
        resp = auth_client.patch(
            f"{RULES_URL}{rule.id}/",
            json.dumps({"keyword": "mine now"}),
            content_type="application/json",
        )
        assert resp.status_code == 404
        resp = auth_client.delete(f"{RULES_URL}{rule.id}/")
        assert resp.status_code == 404
        rule.refresh_from_db()
        assert rule.keyword == "secret"

    @pytest.mark.django_db
    def test_list_scoped_to_user(self, auth_client, user, db):
        other = User.objects.create_user(username="other", password="pass123")
        TravelRule.objects.create(user=other, keyword="theirs")
        TravelRule.objects.create(user=user, keyword="mine")
        rules = auth_client.get(RULES_URL).json()["travel_rules"]
        assert [r["keyword"] for r in rules] == ["mine"]

    @pytest.mark.django_db
    def test_per_user_cap(self, auth_client, user):
        from calendar_sync.travel_rules import MAX_TRAVEL_RULES_PER_USER

        TravelRule.objects.bulk_create(
            TravelRule(user=user, keyword=f"k{i}", order=i)
            for i in range(MAX_TRAVEL_RULES_PER_USER)
        )
        resp = self._create(auth_client, keyword="one too many")
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_unauthenticated_redirects(self, client, db):
        assert client.get(RULES_URL).status_code == 302

    @pytest.mark.django_db
    def test_unauthenticated_create_redirects(self, client, db):
        resp = client.post(
            RULES_URL,
            json.dumps({"keyword": "gym"}),
            content_type="application/json",
        )
        assert resp.status_code == 302
        assert not TravelRule.objects.exists()

    @pytest.mark.django_db
    def test_unauthenticated_detail_verbs_redirect(self, client, user):
        """The write verbs on the detail route are gated too, not just GET."""
        rule = TravelRule.objects.create(user=user, keyword="gym", order=0)
        url = f"{RULES_URL}{rule.id}/"

        patch_resp = client.patch(
            url,
            json.dumps({"keyword": "hijacked"}),
            content_type="application/json",
        )
        assert patch_resp.status_code == 302

        delete_resp = client.delete(url)
        assert delete_resp.status_code == 302

        rule.refresh_from_db()
        assert rule.keyword == "gym"

    @pytest.mark.django_db
    def test_csrf_enforced_on_create(self, csrf_auth_client):
        resp = csrf_auth_client.post(
            RULES_URL,
            json.dumps({"keyword": "gym"}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert not TravelRule.objects.exists()
