"""Integration tests for the ``ai_command`` view.

Each test monkeypatches ``ai.service.run_command`` with a canned result or
error so no network call is made. The view's DB interactions are exercised
for real.
"""
import json

import pytest
from ai.models import AIInteraction
from ai.service import (
    AICommandResult,
    AIParseError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
)
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Rule

URL = "/api/ai/schedules/2026-04-18/command/"


@pytest.fixture
def today_schedule(user):
    return Schedule.objects.create(user=user, date="2026-04-18")


def _post(client, body, url=URL):
    return client.post(url, json.dumps(body), content_type="application/json")


def _patch_run(monkeypatch, behaviour):
    """``behaviour`` is either an ``AICommandResult`` or an exception.

    ``ai.views.run_command`` is async (feature 0009), so the replacement
    must be ``async def`` — the view ``await``s the call.
    """

    async def _run(*args, **kwargs):
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour

    monkeypatch.setattr("ai.views.run_command", _run)


class TestRouting:
    @pytest.mark.django_db
    def test_requires_auth(self, client):
        resp = _post(client, {"command": "hi"})
        assert resp.status_code == 302

    @pytest.mark.django_db
    def test_invalid_date(self, auth_client):
        resp = _post(auth_client, {"command": "hi"}, url="/api/ai/schedules/not-a-date/command/")
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_invalid_json_body(self, auth_client):
        resp = auth_client.post(URL, "{", content_type="application/json")
        assert resp.status_code == 400

    @pytest.mark.django_db
    @pytest.mark.parametrize("raw_body", ["[]", '"x"', "123", "null", "true"])
    def test_non_dict_json_body(self, auth_client, raw_body):
        """Lock the contract that malformed bodies always return 4xx, never 5xx.

        Valid JSON with a non-dict root (``[]``, ``"x"``, ``123``,
        ``null``, ``true``) parses cleanly via ``json.loads`` but would
        crash on ``data.get("command")`` with ``AttributeError`` → 500
        without the explicit ``isinstance(data, dict)`` guard added in
        ``backend/ai/views.py`` (the post-JSON-parse step). Mirrors the
        same contract enforced for ``ai_chat`` in
        ``test_ai_views_chat.py::test_non_object_json_root_returns_400``.
        """
        resp = auth_client.post(URL, raw_body, content_type="application/json")
        assert resp.status_code == 400
        assert resp.json()["errors"]["body"] == "Request body must be a JSON object."

    @pytest.mark.django_db
    def test_non_string_command(self, auth_client):
        resp = _post(auth_client, {"command": 42})
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_oversized_body(self, auth_client):
        resp = auth_client.post(
            URL,
            json.dumps({"command": "x" * 200_000}),
            content_type="application/json",
        )
        assert resp.status_code == 413


class TestHappyPaths:
    @pytest.mark.django_db
    def test_add_action(self, auth_client, today_schedule, monkeypatch):
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text='{"actions":[...],"explanation":"ok"}',
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Standup",
                        "start_time": "10:00",
                        "end_time": "10:15",
                        "category": "work",
                    }
                ],
                explanation="Added standup",
            ),
        )
        resp = _post(auth_client, {"command": "add standup at 10"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["explanation"] == "Added standup"
        assert len(data["blocks"]) == 1
        assert data["blocks"][0]["title"] == "Standup"
        # Intent logged exactly once.
        assert AIInteraction.objects.filter(schedule=today_schedule).count() == 1

    @pytest.mark.django_db
    def test_move_preserves_duration(self, auth_client, today_schedule, monkeypatch):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Gym",
            start_time="17:00",
            end_time="18:00",
            category="health",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {"type": "move", "task_id": block.id, "start_time": "19:00"}
                ],
                explanation="Moved gym",
            ),
        )
        resp = _post(auth_client, {"command": "move gym to 19:00"})
        assert resp.status_code == 200
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "19:00"
        assert block.end_time.strftime("%H:%M") == "20:00"  # duration preserved

    @pytest.mark.django_db
    def test_remove_action(self, auth_client, today_schedule, monkeypatch):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="X",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "remove", "task_id": block.id}],
                explanation="Removed X",
            ),
        )
        resp = _post(auth_client, {"command": "delete X"})
        assert resp.status_code == 200
        assert not TimeBlock.objects.filter(pk=block.id).exists()

    @pytest.mark.django_db
    def test_resize_action(self, auth_client, today_schedule, monkeypatch):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="X",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {"type": "resize", "task_id": block.id, "end_time": "10:30"}
                ],
                explanation="Extended",
            ),
        )
        resp = _post(auth_client, {"command": "make X 30 min longer"})
        assert resp.status_code == 200
        block.refresh_from_db()
        assert block.end_time.strftime("%H:%M") == "10:30"


class TestFailures:
    @pytest.mark.django_db
    def test_missing_api_key_returns_503(self, auth_client, today_schedule, monkeypatch):
        _patch_run(monkeypatch, AIUnavailableError("no key"))
        resp = _post(auth_client, {"command": "add standup"})
        assert resp.status_code == 503
        # Still logged.
        assert AIInteraction.objects.filter(schedule=today_schedule).count() == 1

    @pytest.mark.django_db
    def test_timeout_returns_504(self, auth_client, today_schedule, monkeypatch):
        _patch_run(monkeypatch, AITimeoutError("slow"))
        resp = _post(auth_client, {"command": "add standup"})
        assert resp.status_code == 504
        assert AIInteraction.objects.filter(schedule=today_schedule).count() == 1

    @pytest.mark.django_db
    def test_provider_error_returns_502(self, auth_client, today_schedule, monkeypatch):
        _patch_run(monkeypatch, AIProviderError("auth failed"))
        resp = _post(auth_client, {"command": "add standup"})
        assert resp.status_code == 502

    @pytest.mark.django_db
    def test_cross_user_task_id_returns_400(
        self, auth_client, today_schedule, monkeypatch
    ):
        other_user = User.objects.create_user(username="other", password="x")
        other_schedule = Schedule.objects.create(user=other_user, date="2026-04-18")
        other_block = TimeBlock.objects.create(
            schedule=other_schedule,
            title="secret",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "remove", "task_id": other_block.id}],
                explanation="Removed",
            ),
        )
        resp = _post(auth_client, {"command": "remove that block"})
        assert resp.status_code == 400
        # Other user's block still exists — no side effects.
        assert TimeBlock.objects.filter(pk=other_block.id).exists()
        # Intent was still logged on the caller's schedule.
        assert AIInteraction.objects.filter(schedule=today_schedule).count() == 1

    @pytest.mark.django_db
    def test_mid_batch_failure_rolls_back(
        self, auth_client, today_schedule, monkeypatch
    ):
        """Second action fails → first action's changes roll back, but the
        AIInteraction row for the intent still exists."""
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "A",
                        "start_time": "09:00",
                        "end_time": "09:30",
                        "category": "work",
                    },
                    # Overlap: same window → should fail after A was added.
                    {
                        "type": "add",
                        "title": "B",
                        "start_time": "09:00",
                        "end_time": "09:30",
                        "category": "work",
                    },
                ],
                explanation="Two",
            ),
        )
        resp = _post(auth_client, {"command": "add two"})
        assert resp.status_code == 400
        assert TimeBlock.objects.filter(schedule=today_schedule).count() == 0
        assert AIInteraction.objects.filter(schedule=today_schedule).count() == 1


class TestCsrf:
    @pytest.mark.django_db
    def test_without_csrf_token_returns_403(self, csrf_auth_client):
        resp = _post(csrf_auth_client, {"command": "hi"})
        assert resp.status_code == 403


class TestBilingual:
    @pytest.mark.django_db
    def test_russian_command_round_trips(
        self, auth_client, today_schedule, monkeypatch
    ):
        """Cyrillic in both ``command`` and ``explanation`` passes through
        end-to-end without encoding loss."""
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text='{"actions":[],"explanation":"Готово"}',
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Тренировка",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "category": "health",
                    }
                ],
                explanation="Готово",
            ),
        )
        resp = _post(
            auth_client, {"command": "Добавь тренировку в 09:00"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["explanation"] == "Готово"
        assert data["blocks"][0]["title"] == "Тренировка"
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert "Добавь" in interaction.user_command
        assert "тренировку" in interaction.user_command


class TestParseErrorLogging:
    @pytest.mark.django_db
    def test_parse_error_returns_502_and_logs_raw(
        self, auth_client, today_schedule, monkeypatch
    ):
        raw = '{"not":"valid"}'
        _patch_run(
            monkeypatch,
            AIParseError("envelope missing actions", raw_response_text=raw),
        )
        resp = _post(auth_client, {"command": "add standup"})
        assert resp.status_code == 502
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert interaction.ai_response == raw
        assert interaction.actions_json == []


class TestAddOverlapRejection:
    @pytest.mark.django_db
    def test_add_rejected_when_overlapping_existing_block(
        self, auth_client, today_schedule, monkeypatch
    ):
        TimeBlock.objects.create(
            schedule=today_schedule,
            title="Deep work",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Standup",
                        "start_time": "09:30",
                        "end_time": "10:30",
                        "category": "work",
                    }
                ],
                explanation="Added",
            ),
        )
        resp = _post(auth_client, {"command": "add standup at 09:30"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["errors"]["action_index"] == 0
        # Existing block unchanged; new block not created.
        assert TimeBlock.objects.filter(schedule=today_schedule).count() == 1


class TestGranularity:
    @pytest.mark.django_db
    def test_move_rejects_non_five_minute_start(
        self, auth_client, today_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Gym",
            start_time="09:00",
            end_time="10:00",
            category="health",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {"type": "move", "task_id": block.id, "start_time": "09:07"}
                ],
                explanation="Moved",
            ),
        )
        resp = _post(auth_client, {"command": "move gym to 09:07"})
        assert resp.status_code == 400
        assert resp.json()["errors"]["action_index"] == 0
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "09:00"

    @pytest.mark.django_db
    def test_resize_rejects_non_five_minute_end(
        self, auth_client, today_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Gym",
            start_time="09:00",
            end_time="10:00",
            category="health",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {"type": "resize", "task_id": block.id, "end_time": "10:13"}
                ],
                explanation="Resized",
            ),
        )
        resp = _post(auth_client, {"command": "resize gym to 10:13"})
        assert resp.status_code == 400
        assert resp.json()["errors"]["action_index"] == 0


class TestOversizedCommand:
    @pytest.mark.django_db
    def test_oversized_command_returns_400(
        self, auth_client, today_schedule, monkeypatch, settings
    ):
        """A command under the body-size cap (100 KB) but over the chars cap
        (default 500) is an ``AIInvalidInputError`` from ``run_command``
        mapped to a 400 by the view."""
        settings.LLM_API_KEY = "test-key"
        # 600 chars — under 100 KB body cap, over the 500-char command cap.
        long = "x" * 600
        resp = _post(auth_client, {"command": long})
        assert resp.status_code == 400
        # Interaction logged (command only, since run_command raised before
        # producing a response).
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert interaction.user_command == long


class TestInteractionTruncation:
    @pytest.mark.django_db
    def test_log_truncates_oversized_response(
        self, auth_client, today_schedule, monkeypatch
    ):
        """A pathological 50 KB raw response is truncated to 10 KB in the
        ``AIInteraction`` row (see ``_MAX_AI_RESPONSE_LOG_LEN``)."""
        huge = "A" * 50_000
        _patch_run(
            monkeypatch,
            AIParseError("too much", raw_response_text=huge),
        )
        resp = _post(auth_client, {"command": "do it"})
        assert resp.status_code == 502
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert len(interaction.ai_response) == 10_000
        assert interaction.ai_response == "A" * 10_000


class TestMidnightWrap:
    @pytest.mark.django_db
    def test_duration_preserving_move_past_midnight_returns_clear_error(
        self, auth_client, today_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Gym",
            start_time="22:00",
            end_time="23:30",
            category="health",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {"type": "move", "task_id": block.id, "start_time": "23:00"}
                ],
                explanation="Moved",
            ),
        )
        resp = _post(auth_client, {"command": "move gym to 23:00"})
        assert resp.status_code == 400
        assert (
            resp.json()["errors"]["detail"]
            == "moved block would extend past midnight"
        )
        # Block untouched.
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "22:00"
        assert block.end_time.strftime("%H:%M") == "23:30"


class TestDayWindow:
    """Server-side enforcement of the [06:00, 23:00] working-day window."""

    @pytest.mark.django_db
    def test_add_rejected_when_start_before_day_start(
        self, auth_client, today_schedule, monkeypatch
    ):
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Pre-dawn standup",
                        "start_time": "05:30",
                        "end_time": "06:00",
                        "category": "work",
                    }
                ],
                explanation="Before the day starts",
            ),
        )
        resp = _post(auth_client, {"command": "add standup at 5:30"})
        assert resp.status_code == 400
        assert resp.json()["errors"]["action_index"] == 0
        assert "06:00" in resp.json()["errors"]["detail"]
        assert TimeBlock.objects.count() == 0

    @pytest.mark.django_db
    def test_add_rejected_when_end_after_day_end(
        self, auth_client, today_schedule, monkeypatch
    ):
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Late work",
                        "start_time": "22:30",
                        "end_time": "23:30",
                        "category": "work",
                    }
                ],
                explanation="Past close of day",
            ),
        )
        resp = _post(auth_client, {"command": "add work til 23:30"})
        assert resp.status_code == 400
        assert resp.json()["errors"]["action_index"] == 0
        assert "23:00" in resp.json()["errors"]["detail"]
        assert TimeBlock.objects.count() == 0

    @pytest.mark.django_db
    def test_add_accepted_at_day_boundaries(
        self, auth_client, today_schedule, monkeypatch
    ):
        """06:00 start and 23:00 end are inclusive edges."""
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Full day",
                        "start_time": "06:00",
                        "end_time": "23:00",
                        "category": "work",
                    }
                ],
                explanation="All day",
            ),
        )
        resp = _post(auth_client, {"command": "block the whole day"})
        assert resp.status_code == 200
        assert TimeBlock.objects.count() == 1

    @pytest.mark.django_db
    def test_resize_rejected_when_end_after_day_end(
        self, auth_client, today_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Work",
            start_time="22:00",
            end_time="22:30",
            category="work",
        )
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {"type": "resize", "task_id": block.id, "end_time": "23:30"}
                ],
                explanation="Extend",
            ),
        )
        resp = _post(auth_client, {"command": "extend work to 23:30"})
        assert resp.status_code == 400
        assert "23:00" in resp.json()["errors"]["detail"]
        block.refresh_from_db()
        assert block.end_time.strftime("%H:%M") == "22:30"


class TestRateLimit:
    @pytest.mark.django_db
    def test_returns_429_once_budget_is_exceeded(
        self, auth_client, today_schedule, monkeypatch, settings
    ):
        settings.LLM_RATE_LIMIT_PER_HOUR = 2
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="ok",
            ),
        )
        assert _post(auth_client, {"command": "one"}).status_code == 200
        assert _post(auth_client, {"command": "two"}).status_code == 200

        resp = _post(auth_client, {"command": "three"})
        assert resp.status_code == 429
        assert "rate limit" in resp.json()["errors"]["detail"].lower()
        # 429 short-circuits before the LLM path, so no extra interaction row
        # is written for the rejected request.
        assert AIInteraction.objects.count() == 2

    @pytest.mark.django_db
    def test_cache_incr_value_error_reseeds_counter(
        self, auth_client, today_schedule, monkeypatch
    ):
        """If the key evicts between ``cache.aadd`` returning False and the
        increment firing, the sync ``cache.incr`` raises ``ValueError``.
        The decorator must recover by re-seeding the counter, not 500.

        (Feature 0015: ``_consume_rate_limit`` routes the increment through
        the **sync** ``cache.incr`` via ``sync_to_async`` — for atomic
        Redis ``INCR`` + TTL preservation — so the replacement is a plain
        ``def``, not ``async def``.)"""
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="ok",
            ),
        )
        # Seed the cache with a first successful call.
        assert _post(auth_client, {"command": "seed"}).status_code == 200

        def _raise_value_error(_key):
            raise ValueError("key missing")

        monkeypatch.setattr("ai.views.cache.incr", _raise_value_error)
        # Second call enters the ``incr`` branch, hits ValueError, and
        # the except clause re-seeds the counter so the request succeeds.
        resp = _post(auth_client, {"command": "after-evict"})
        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_increment_preserves_window_ttl(
        self, auth_client, user, today_schedule, monkeypatch, settings
    ):
        """Regression (feature 0015, M1): incrementing the counter must NOT
        reset the fixed window TTL.

        The window is anchored by ``cache.aadd(key, 1, 3600)``. The async
        ``cache.aincr`` (non-atomic ``aget``→``aset``) would rewrite the
        TTL to ``default_timeout`` (300s) on every request, silently
        shrinking the window; the sync ``cache.incr`` the code now uses
        (atomic ``INCR`` on Redis; in-place on LocMem) leaves it intact.

        Observed on the pinned LocMem backend via ``_expire_info``. The
        atomicity half of the fix (H1) needs concurrent Redis and is out of
        the unit suite, but TTL preservation is observable here: a
        TTL-resetting increment would leave ~300s instead of ~3600s."""
        import time

        from django.core.cache import cache

        settings.LLM_RATE_LIMIT_PER_HOUR = 100
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="ok",
            ),
        )
        key = cache.make_key(f"ai_cmd_rl:{user.id}")
        assert _post(auth_client, {"command": "one"}).status_code == 200  # aadd -> 3600s
        assert _post(auth_client, {"command": "two"}).status_code == 200  # incr
        # ``_expire_info`` is a LocMemCache implementation detail; this read
        # only works because conftest's ``_pin_test_cache_backend`` pins the
        # suite to LocMem (the unit suite never talks to Redis), and would
        # break if Django changed LocMem's expiry internals.
        ttl_remaining = cache._expire_info[key] - time.time()
        # 3600s window; a reset-to-default-timeout bug would show ~300s.
        assert ttl_remaining > 1800

    @pytest.mark.django_db
    def test_counter_stored_under_expected_key(
        self, auth_client, user, today_schedule, monkeypatch, settings
    ):
        """Key-shape regression (feature 0015): the command counter is
        stored under ``ai_cmd_rl:<user_id>`` and increments per request.

        Redis's ``KEY_PREFIX`` (``dayforge``) is transparent to
        ``cache.get``, so this assertion holds on the pinned LocMem suite
        and on a Redis-backed integration run alike. This is deliberately
        NOT a cross-worker test: two ``Client`` instances in one process
        share LocMem / FileBased / Dummy, so a "two clients, one counter"
        assertion would pass on the exact broken configurations ``ai.E001``
        guards against and would prove nothing about multi-worker
        behaviour. Cross-worker enforcement is covered by the hardened
        ``test_checks.py`` cases plus an optional Redis integration step
        (see 0015 plan Phase 3)."""
        from django.core.cache import cache

        settings.LLM_RATE_LIMIT_PER_HOUR = 5
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="ok",
            ),
        )
        assert cache.get(f"ai_cmd_rl:{user.id}") is None
        assert _post(auth_client, {"command": "one"}).status_code == 200
        assert cache.get(f"ai_cmd_rl:{user.id}") == 1
        assert _post(auth_client, {"command": "two"}).status_code == 200
        assert cache.get(f"ai_cmd_rl:{user.id}") == 2


class TestActiveRulesWiring:
    """Feature 0012: ``ai_command`` must pass only the authenticated
    user's ACTIVE rules to ``run_command``, ordered by ``-priority``.

    Inactive rules and other users' rules must be filtered out at the
    view/query layer (``_load_active_rules``). Prompt builders render
    whatever they're handed, so this filtering is a view-level invariant.
    """

    @pytest.mark.django_db
    def test_only_authenticated_users_active_rules_are_passed(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        # Active rules for the authenticated user — both should be passed,
        # high-priority first.
        Rule.objects.create(
            user=user, text="HIGH rule", priority=10, is_active=True
        )
        Rule.objects.create(
            user=user, text="LOW rule", priority=1, is_active=True
        )
        # Inactive rule for same user — must be filtered out.
        Rule.objects.create(
            user=user, text="INACTIVE", priority=99, is_active=False
        )
        # Active rule for OTHER user — must be filtered out.
        other_user = User.objects.create_user(username="other", password="x")
        Rule.objects.create(
            user=other_user, text="OTHER USER", priority=99, is_active=True
        )

        captured = {}

        async def _capture(command, schedule, blocks, rules, now):
            captured["rules_texts"] = [r.text for r in rules]
            return AICommandResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="ok",
            )

        monkeypatch.setattr("ai.views.run_command", _capture)
        resp = _post(auth_client, {"command": "do thing"})
        assert resp.status_code == 200
        # Exactly the two active, user-owned rules, ordered high → low.
        assert captured["rules_texts"] == ["HIGH rule", "LOW rule"]


@pytest.mark.django_db
class TestApplyActionsLocksScheduleRow:
    """Regression: the command/chat apply path must lock the parent
    ``Schedule`` row so it serializes with ``_apply_draft_sync`` on an
    empty day — locking only the (empty) ``TimeBlock`` queryset acquires
    zero rows."""

    def test_locks_schedule_row(
        self, auth_client, today_schedule, monkeypatch
    ):
        _patch_run(
            monkeypatch,
            AICommandResult(
                raw_response_text="{}",
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Standup",
                        "start_time": "10:00",
                        "end_time": "10:15",
                        "category": "work",
                    }
                ],
                explanation="Added standup",
            ),
        )
        original = Schedule.objects.select_for_update
        called = {"v": False}

        def _spy(*args, **kwargs):
            called["v"] = True
            return original(*args, **kwargs)

        monkeypatch.setattr(
            Schedule.objects, "select_for_update", _spy, raising=True
        )
        resp = _post(auth_client, {"command": "add standup at 10"})
        assert resp.status_code == 200, resp.content
        assert called["v"]
