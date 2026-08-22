"""Integration tests for the ``ai_chat`` multi-turn view (feature 0007).

Each test monkeypatches ``ai.service.run_chat`` with a canned result or
error so no network call is made. The view's validation order, audit
logging shape, rate-limit independence, and untrusted-transcript
handling are all exercised against real DB.
"""

import datetime
import hashlib
import json

import pytest
from ai.models import AIInteraction
from ai.mutation_planner import ActionOutcome
from ai.service import (
    AIChatResult,
    AIInvalidInputError,
    AIParseError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
)
from ai.views import _build_resolution_ask
from asgiref.sync import sync_to_async
from django.contrib.auth.models import User
from django.core.cache import cache
from schedules.models import Schedule, TimeBlock, UserScheduleSettings
from templates_mgr.models import Rule

URL = "/api/ai/schedules/2026-04-18/chat/"


def _set_window(user, day_start, day_end):
    """Seed the per-user schedule window (feature 0053).

    ``_apply_actions_sync`` resolves the window under its apply lock via
    ``get_schedule_window`` → ``UserScheduleSettings`` (default 06:00–23:00),
    so a DB row is how a non-default window reaches the planner in these
    integration tests. ``update_or_create`` keeps the row valid (save() runs
    full_clean).
    """
    UserScheduleSettings.objects.update_or_create(
        user=user, defaults={"day_start": day_start, "day_end": day_end}
    )


@pytest.fixture
def today_schedule(user):
    return Schedule.objects.create(user=user, date="2026-04-18")


def _post(client, body, url=URL):
    return client.post(url, json.dumps(body), content_type="application/json")


def _patch_run_chat(monkeypatch, behaviour):
    """``behaviour`` is either an ``AIChatResult`` or an exception.

    ``ai.views.run_chat`` is async (feature 0009) — replacement must be ``async def``.
    """

    async def _run(*args, **kwargs):
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour

    monkeypatch.setattr("ai.views.run_chat", _run)


def _user_turn(text):
    return {"role": "user", "content": text}


def _assistant_turn(text):
    return {"role": "assistant", "content": text}


class TestValidation:
    @pytest.mark.django_db
    def test_requires_auth(self, client):
        resp = _post(client, {"messages": [_user_turn("hi")]})
        assert resp.status_code == 302

    @pytest.mark.django_db
    def test_invalid_date(self, auth_client):
        resp = _post(
            auth_client,
            {"messages": [_user_turn("hi")]},
            url="/api/ai/schedules/not-a-date/chat/",
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_invalid_json_body(self, auth_client):
        resp = auth_client.post(URL, "{", content_type="application/json")
        assert resp.status_code == 400
        assert resp.json() == {"errors": {"body": "Invalid JSON."}}

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "body",
        [
            "[]",
            '"x"',
            "123",
            "null",
            "true",
            "false",
        ],
    )
    def test_non_object_json_root_returns_400(self, auth_client, body):
        """Lock the contract that malformed bodies always return 4xx, never 5xx.

        Valid JSON with a non-dict root (``[]``, ``"x"``, ``123``,
        ``null``, ``true``, ``false``) parses cleanly via ``json.loads`` but would
        crash on ``data.get("messages")`` with ``AttributeError`` → 500
        without the explicit ``isinstance(data, dict)`` guard added in
        ``backend/ai/views.py`` (the post-JSON-parse step). This test
        exercises every primitive root form the bot found that a 500
        was reachable from valid JSON.
        """
        resp = auth_client.post(URL, body, content_type="application/json")
        assert resp.status_code == 400
        payload = resp.json()
        assert "errors" in payload

    @pytest.mark.django_db
    def test_messages_missing(self, auth_client):
        resp = _post(auth_client, {"foo": "bar"})
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_empty_messages(self, auth_client):
        resp = _post(auth_client, {"messages": []})
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_non_alternating_roles(self, auth_client):
        resp = _post(
            auth_client,
            {"messages": [_user_turn("hi"), _user_turn("again")]},
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_last_role_assistant(self, auth_client):
        resp = _post(
            auth_client,
            {
                "messages": [
                    _user_turn("hi"),
                    _assistant_turn("yes?"),
                ]
            },
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_first_role_assistant(self, auth_client):
        resp = _post(
            auth_client,
            {"messages": [_assistant_turn("howdy"), _user_turn("hi")]},
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_per_message_cap(self, auth_client, settings):
        settings.LLM_MAX_COMMAND_CHARS = 10
        resp = _post(
            auth_client,
            {"messages": [_user_turn("x" * 11)]},
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_total_chars_cap(self, auth_client, settings):
        settings.LLM_MAX_COMMAND_CHARS = 100
        settings.LLM_CHAT_MAX_TOTAL_CHARS = 50
        resp = _post(
            auth_client,
            {
                "messages": [
                    _user_turn("a" * 30),
                    _assistant_turn("b" * 30),
                    _user_turn("c" * 30),
                ]
            },
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_total_chars_cap_boundary_equal_passes(
        self, today_schedule, auth_client, monkeypatch, settings
    ):
        """Boundary: total content length exactly equal to the cap MUST pass.

        The validator uses ``>`` not ``>=`` so a transcript whose
        cumulative ``content`` length lands exactly on
        ``LLM_CHAT_MAX_TOTAL_CHARS`` is valid input. This locks in the
        off-by-one direction.
        """
        settings.LLM_MAX_COMMAND_CHARS = 100
        settings.LLM_CHAT_MAX_TOTAL_CHARS = 50
        # Stub the LLM call so the request can reach the success branch
        # — the test is about validation, not provider behaviour.
        from ai.service import AIChatResult

        async def _ok(*a, **kw):
            return AIChatResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="",
                ask=None,
            )

        monkeypatch.setattr("ai.views.run_chat", _ok)
        # 20 + 15 + 15 = 50 exactly.
        resp = _post(
            auth_client,
            {
                "messages": [
                    _user_turn("a" * 20),
                    _assistant_turn("b" * 15),
                    _user_turn("c" * 15),
                ]
            },
        )
        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_max_turns_cap(self, auth_client, settings):
        settings.LLM_CHAT_MAX_TURNS = 3
        resp = _post(
            auth_client,
            {
                "messages": [
                    _user_turn("1"),
                    _assistant_turn("2"),
                    _user_turn("3"),
                    _assistant_turn("4"),
                    _user_turn("5"),
                ]
            },
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_max_turns_boundary_equal_passes(
        self, today_schedule, auth_client, monkeypatch, settings
    ):
        """Boundary: exactly LLM_CHAT_MAX_TURNS messages MUST pass.

        Validator uses ``> LLM_CHAT_MAX_TURNS`` so the cap value itself
        is allowed. Locks the off-by-one direction.
        """
        settings.LLM_CHAT_MAX_TURNS = 5
        from ai.service import AIChatResult

        async def _ok(*a, **kw):
            return AIChatResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="",
                ask=None,
            )

        monkeypatch.setattr("ai.views.run_chat", _ok)
        resp = _post(
            auth_client,
            {
                "messages": [
                    _user_turn("1"),
                    _assistant_turn("2"),
                    _user_turn("3"),
                    _assistant_turn("4"),
                    _user_turn("5"),
                ]
            },
        )
        assert resp.status_code == 200

    @pytest.mark.django_db
    def test_max_turns_plus_one_rejected(self, auth_client, settings):
        """Boundary + 1: one over the cap MUST 400."""
        settings.LLM_CHAT_MAX_TURNS = 5
        resp = _post(
            auth_client,
            {
                "messages": [
                    _user_turn("1"),
                    _assistant_turn("2"),
                    _user_turn("3"),
                    _assistant_turn("4"),
                    _user_turn("5"),
                    _assistant_turn("6"),
                    _user_turn("7"),
                ]
            },
        )
        assert resp.status_code == 400

    @pytest.mark.django_db
    def test_oversized_body(self, auth_client):
        # Single message bumps the body past the 1 MB cap.
        resp = auth_client.post(
            URL,
            json.dumps({"messages": [_user_turn("x" * 2_000_000)]}),
            content_type="application/json",
        )
        assert resp.status_code == 413

    @pytest.mark.django_db
    def test_invalid_body_does_not_create_schedule(self, user, auth_client):
        # No Schedule row exists for this user/date yet.
        assert Schedule.objects.filter(user=user, date="2026-04-18").count() == 0
        resp = _post(auth_client, {"messages": [_user_turn("")]})
        assert resp.status_code == 400
        # Validation runs BEFORE get_or_create — no row should be persisted.
        assert Schedule.objects.filter(user=user, date="2026-04-18").count() == 0

    @pytest.mark.django_db
    def test_validation_failures_do_not_consume_rate_limit(self, user, auth_client, settings):
        settings.LLM_CHAT_RATE_LIMIT_PER_HOUR = 5
        # Five malformed bodies in a row — none should burn the budget.
        for _ in range(5):
            resp = _post(auth_client, {"messages": []})
            assert resp.status_code == 400
        # Counter must still be at zero.
        assert cache.get(f"ai_chat_rl:{user.id}") in (None, 0)


class TestClarifyingQuestion:
    @pytest.mark.django_db
    def test_returns_ask_without_mutating(self, user, auth_client, today_schedule, monkeypatch):
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text='{"actions":[],"explanation":"need info","ask":"when?"}',
                parsed_actions=[],
                explanation="need info",
                ask="when?",
            ),
        )
        resp = _post(auth_client, {"messages": [_user_turn("add gym")]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ask"] == "when?"
        assert data["applied"] is False
        assert data["blocks"] is None
        # No blocks created.
        assert TimeBlock.objects.filter(schedule=today_schedule).count() == 0
        # Audit row exists, success=True, empty actions_json.
        rows = list(AIInteraction.objects.filter(schedule=today_schedule))
        assert len(rows) == 1
        assert rows[0].success is True
        assert rows[0].actions_json == []


class TestApply:
    @pytest.mark.django_db
    def test_apply_actions_creates_blocks(self, user, auth_client, today_schedule, monkeypatch):
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text='{"actions":[...],"explanation":"ok","ask":null}',
                parsed_actions=[
                    {
                        "type": "add",
                        "title": "Gym",
                        "start_time": "18:00",
                        "end_time": "19:00",
                        "category": "personal",
                    }
                ],
                explanation="Added",
                ask=None,
            ),
        )
        resp = _post(
            auth_client,
            {"messages": [_user_turn("add gym 18:00-19:00")]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is True
        assert data["ask"] is None
        assert len(data["blocks"]) == 1
        # Status flipped to active.
        today_schedule.refresh_from_db()
        assert today_schedule.status == "active"
        # Audit success.
        row = AIInteraction.objects.get(schedule=today_schedule)
        assert row.success is True

    @pytest.mark.django_db
    def test_chitchat_no_op(self, user, auth_client, today_schedule, monkeypatch):
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text='{"actions":[],"explanation":"you are welcome","ask":null}',
                parsed_actions=[],
                explanation="you are welcome",
                ask=None,
            ),
        )
        resp = _post(auth_client, {"messages": [_user_turn("thanks!")]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is False
        assert data["ask"] is None
        # Status stays as default (draft).
        today_schedule.refresh_from_db()
        assert today_schedule.status == "draft"


class TestRateLimit:
    @pytest.mark.django_db
    def test_chat_bucket_enforces_limit(self, user, auth_client, monkeypatch, settings):
        settings.LLM_CHAT_RATE_LIMIT_PER_HOUR = 1
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="",
                ask=None,
            ),
        )
        # First call OK.
        resp1 = _post(auth_client, {"messages": [_user_turn("hi")]})
        assert resp1.status_code == 200
        # Second call rate-limited.
        resp2 = _post(auth_client, {"messages": [_user_turn("hi again")]})
        assert resp2.status_code == 429
        assert resp2.json()["errors"]["detail"] == "Rate limit exceeded. Try again later."
        assert cache.get(f"ai_chat_rl:{user.id}") == 2
        # 429 short-circuits before the apply/log path, so the rejected request
        # writes no AIInteraction row (only the first OK call logged one).
        assert AIInteraction.objects.count() == 1

    @pytest.mark.django_db
    def test_chat_bucket_independent_of_draft_bucket(
        self, user, auth_client, monkeypatch, settings
    ):
        # A chat call must increment ONLY ai_chat_rl, never the draft bucket —
        # guards against the two literal key strings ("ai_chat_rl" /
        # "ai_draft_rl") being swapped in views.py (a swap would leave chat
        # unmetered and burn the wrong counter). Migrated from the deleted
        # command↔draft cross-bucket isolation test.
        settings.LLM_CHAT_RATE_LIMIT_PER_HOUR = 5
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="",
                ask=None,
            ),
        )
        resp = _post(auth_client, {"messages": [_user_turn("hi")]})
        assert resp.status_code == 200
        assert cache.get(f"ai_chat_rl:{user.id}") == 1
        assert cache.get(f"ai_draft_rl:{user.id}") in (None, 0)


class TestAuditEnvelope:
    @pytest.mark.django_db
    def test_success_envelope_has_transcript_hash(
        self, user, auth_client, today_schedule, monkeypatch
    ):
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text='{"actions":[],"explanation":"hi","ask":null}',
                parsed_actions=[],
                explanation="hi",
                ask=None,
            ),
        )
        messages = [_user_turn("hello")]
        resp = _post(auth_client, {"messages": messages})
        assert resp.status_code == 200
        row = AIInteraction.objects.get(schedule=today_schedule)
        # Chat audit rows must be labeled kind="chat", not the old default
        # "command" (feature 0044: /command/ removed, AIInteraction.Kind.CHAT added).
        assert row.kind == AIInteraction.Kind.CHAT
        payload = json.loads(row.ai_response)
        expected = hashlib.sha256(
            json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert payload["transcript_sha256"] == expected
        assert payload["turn_count"] == 1
        assert "raw" in payload
        assert "error_class" not in payload

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "exc, expected_status",
        [
            (AIUnavailableError("no key"), 503),
            (AITimeoutError("provider slow"), 504),
            (AIProviderError("auth failed"), 502),
            (AIInvalidInputError("bad input"), 400),
            (AIParseError("bad json", raw_response_text="not-json"), 502),
        ],
    )
    def test_failure_envelope_carries_error_class(
        self,
        user,
        auth_client,
        today_schedule,
        monkeypatch,
        exc,
        expected_status,
    ):
        _patch_run_chat(monkeypatch, exc)
        messages = [_user_turn("anything")]
        resp = _post(auth_client, {"messages": messages})
        assert resp.status_code == expected_status
        rows = list(AIInteraction.objects.filter(schedule=today_schedule))
        assert len(rows) == 1
        row = rows[0]
        assert row.success is False
        assert row.actions_json == []
        payload = json.loads(row.ai_response)
        expected_hash = hashlib.sha256(
            json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        assert payload["transcript_sha256"] == expected_hash
        assert payload["turn_count"] == 1
        assert payload["error_class"] == type(exc).__name__
        if isinstance(exc, AIParseError):
            assert payload["raw"] == "not-json"
        else:
            assert payload["raw"] == str(exc)


class TestActiveRulesWiring:
    """Feature 0012: ``ai_chat`` must pass only the authenticated user's
    ACTIVE rules to ``run_chat``, ordered by ``-priority``. Mirrors the
    draft endpoint's rule-loading contract (``test_ai_views_draft.TestActiveRulesWiring``)
    so chat and draft can't drift.
    """

    @pytest.mark.django_db
    def test_only_authenticated_users_active_rules_are_passed(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        Rule.objects.create(user=user, text="HIGH rule", priority=10, is_active=True)
        Rule.objects.create(user=user, text="LOW rule", priority=1, is_active=True)
        Rule.objects.create(user=user, text="INACTIVE", priority=99, is_active=False)
        other_user = User.objects.create_user(username="other", password="x")
        Rule.objects.create(user=other_user, text="OTHER USER", priority=99, is_active=True)

        captured = {}

        async def _capture(messages, schedule, blocks, rules, now):
            captured["rules_texts"] = [r.text for r in rules]
            return AIChatResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="",
                ask=None,
            )

        monkeypatch.setattr("ai.views.run_chat", _capture)
        resp = _post(auth_client, {"messages": [_user_turn("hi")]})
        assert resp.status_code == 200
        assert captured["rules_texts"] == ["HIGH rule", "LOW rule"]


# --- Slice 5: chat apply + regression guards (feature 0030) ---


class TestChatBatchMutationExecutor:
    """Shared ``_apply_actions_sync`` path through ``/chat/``."""

    @pytest.mark.django_db
    def test_chat_overlap_rolls_back_and_preserves_status(
        self, auth_client, today_schedule, monkeypatch
    ):
        seeded_block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Deep work",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        # Seed REVIEWED so the "status unchanged" assertion discriminates: a
        # successful apply would call mark_active_on_edit() (reviewed -> active),
        # so status staying REVIEWED proves the rejected apply rolled back before
        # that line.
        today_schedule.status = Schedule.Status.REVIEWED
        today_schedule.save(update_fields=["status"])
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
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
                ask=None,
            ),
        )

        resp = _post(
            auth_client,
            {"messages": [_user_turn("add standup at 09:30")]},
        )

        assert resp.status_code == 200
        assert resp.json()["applied"] is False
        assert resp.json()["ask"]
        surviving_blocks = list(TimeBlock.objects.filter(schedule=today_schedule))
        assert [block.pk for block in surviving_blocks] == [seeded_block.pk]
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert interaction.success is True
        today_schedule.refresh_from_db()
        assert today_schedule.status == Schedule.Status.REVIEWED

    @pytest.mark.django_db
    def test_chat_apply_uses_shared_planner(self, auth_client, today_schedule, monkeypatch):
        block_a = TimeBlock.objects.create(
            schedule=today_schedule,
            title="A",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        block_b = TimeBlock.objects.create(
            schedule=today_schedule,
            title="B",
            start_time="11:00",
            end_time="12:00",
            category="work",
        )
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text="{}",
                parsed_actions=[
                    {
                        "type": "move",
                        "task_id": block_a.id,
                        "start_time": "11:00",
                        "end_time": "12:00",
                    },
                    {
                        "type": "move",
                        "task_id": block_b.id,
                        "start_time": "09:00",
                        "end_time": "10:00",
                    },
                ],
                explanation="Swapped A and B",
                ask=None,
            ),
        )
        resp = _post(
            auth_client,
            {"messages": [_user_turn("swap A and B")]},
        )
        assert resp.status_code == 200, resp.content
        data = resp.json()
        assert data["applied"] is True
        block_a.refresh_from_db()
        block_b.refresh_from_db()
        assert block_a.start_time.strftime("%H:%M") == "11:00"
        assert block_a.end_time.strftime("%H:%M") == "12:00"
        assert block_b.start_time.strftime("%H:%M") == "09:00"
        assert block_b.end_time.strftime("%H:%M") == "10:00"
        today_schedule.refresh_from_db()
        assert today_schedule.status == "active"

    @pytest.mark.django_db
    def test_chat_apply_returns_409_when_schedule_changes_during_run_chat(
        self, auth_client, today_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Gym",
            start_time="09:00",
            end_time="10:00",
            category="health",
        )

        async def _run(messages, schedule, blocks, rules, now):
            await sync_to_async(
                TimeBlock.objects.filter(pk=block.pk).update,
                thread_sensitive=True,
            )(title="Renamed during LLM")
            return AIChatResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "move", "task_id": block.id, "start_time": "11:00"}],
                explanation="Moved",
                ask=None,
            )

        monkeypatch.setattr("ai.views.run_chat", _run)
        resp = _post(
            auth_client,
            {"messages": [_user_turn("move gym")]},
        )
        assert resp.status_code == 409
        assert resp.json()["errors"]["detail"] == "schedule_changed"
        block.refresh_from_db()
        assert block.title == "Renamed during LLM"
        assert block.start_time.strftime("%H:%M") == "09:00"
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert interaction.success is False
        today_schedule.refresh_from_db()
        assert today_schedule.status == Schedule.Status.DRAFT

    @pytest.mark.django_db
    def test_chat_apply_returns_409_when_rule_changes_during_run_chat(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Work",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        rule = Rule.objects.create(user=user, text="Original rule", priority=5, is_active=True)

        async def _run(messages, schedule, blocks, rules, now):
            await sync_to_async(
                Rule.objects.filter(pk=rule.pk).update,
                thread_sensitive=True,
            )(text="Changed during LLM")
            return AIChatResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "move", "task_id": block.id, "start_time": "11:00"}],
                explanation="Moved",
                ask=None,
            )

        monkeypatch.setattr("ai.views.run_chat", _run)
        resp = _post(
            auth_client,
            {"messages": [_user_turn("move work")]},
        )
        assert resp.status_code == 409
        assert resp.json()["errors"]["detail"] == "schedule_changed"
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "09:00"
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert interaction.success is False
        today_schedule.refresh_from_db()
        assert today_schedule.status == Schedule.Status.DRAFT

    @pytest.mark.django_db
    def test_chat_empty_actions_skips_apply_on_fingerprint_mismatch(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        rule = Rule.objects.create(user=user, text="Original rule", priority=5, is_active=True)
        apply_called = {"v": False}
        original_apply = None

        async def _run(messages, schedule, blocks, rules, now):
            await sync_to_async(
                Rule.objects.filter(pk=rule.pk).update,
                thread_sensitive=True,
            )(text="Changed during LLM")
            return AIChatResult(
                raw_response_text="{}",
                parsed_actions=[],
                explanation="Nothing to do",
                ask=None,
            )

        def _spy_apply(schedule, result, *, expected_fingerprint, interaction_id=None):
            apply_called["v"] = True
            return original_apply(
                schedule,
                result,
                expected_fingerprint=expected_fingerprint,
                interaction_id=interaction_id,
            )

        monkeypatch.setattr("ai.views.run_chat", _run)
        import ai.views

        original_apply = ai.views._apply_actions_sync
        monkeypatch.setattr(ai.views, "_apply_actions_sync", _spy_apply)

        resp = _post(
            auth_client,
            {"messages": [_user_turn("thanks")]},
        )
        assert resp.status_code == 200
        assert apply_called["v"] is False
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert interaction.success is True
        data = resp.json()
        assert data["applied"] is False
        assert data["blocks"] is None


@pytest.mark.django_db
class TestSharedApplyCoverage:
    """Coverage retained from the removed one-shot endpoint suite."""

    def test_move_preserves_duration(self, auth_client, today_schedule, monkeypatch):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Gym",
            start_time="17:00",
            end_time="18:00",
            category="health",
        )
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "move", "task_id": block.id, "start_time": "19:00"}],
                explanation="Moved gym",
                ask=None,
            ),
        )
        resp = _post(auth_client, {"messages": [_user_turn("move gym")]})
        assert resp.status_code == 200
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "19:00"
        assert block.end_time.strftime("%H:%M") == "20:00"

    def test_remove_action(self, auth_client, today_schedule, monkeypatch):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="X",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "remove", "task_id": block.id}],
                explanation="Removed X",
                ask=None,
            ),
        )
        resp = _post(auth_client, {"messages": [_user_turn("delete X")]})
        assert resp.status_code == 200
        assert not TimeBlock.objects.filter(pk=block.id).exists()

    def test_resize_action(self, auth_client, today_schedule, monkeypatch):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="X",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "resize", "task_id": block.id, "end_time": "10:30"}],
                explanation="Extended",
                ask=None,
            ),
        )
        resp = _post(auth_client, {"messages": [_user_turn("extend X")]})
        assert resp.status_code == 200
        block.refresh_from_db()
        assert block.end_time.strftime("%H:%M") == "10:30"

    def test_cross_user_task_id_returns_400(self, auth_client, today_schedule, monkeypatch):
        other_user = User.objects.create_user(username="other", password="x")
        other_schedule = Schedule.objects.create(user=other_user, date="2026-04-18")
        other_block = TimeBlock.objects.create(
            schedule=other_schedule,
            title="secret",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "remove", "task_id": other_block.id}],
                explanation="Removed",
                ask=None,
            ),
        )
        resp = _post(auth_client, {"messages": [_user_turn("remove it")]})
        assert resp.status_code == 400
        assert TimeBlock.objects.filter(pk=other_block.id).exists()
        assert AIInteraction.objects.filter(schedule=today_schedule).count() == 1

    def test_mid_batch_failure_rolls_back(self, auth_client, today_schedule, monkeypatch):
        actions = [
            {
                "type": "add",
                "title": title,
                "start_time": "09:00",
                "end_time": "09:30",
                "category": "work",
            }
            for title in ("A", "B")
        ]
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", actions, "Two", None),
        )
        resp = _post(auth_client, {"messages": [_user_turn("add two")]})
        assert resp.status_code == 200
        # Two requested creates collide; the order-invariant planner declines
        # both rather than selecting an arbitrary winner.
        assert TimeBlock.objects.filter(schedule=today_schedule).count() == 0
        assert AIInteraction.objects.filter(schedule=today_schedule).count() == 1

    def test_russian_turn_round_trips(self, auth_client, today_schedule, monkeypatch):
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
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
                ask=None,
            ),
        )
        resp = _post(
            auth_client,
            {"messages": [_user_turn("Добавь тренировку в 09:00")]},
        )
        assert resp.status_code == 200
        assert resp.json()["explanation"] == "Готово"
        assert resp.json()["blocks"][0]["title"] == "Тренировка"
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert "Добавь" in interaction.user_command

    @pytest.mark.parametrize(
        "action",
        [
            {"type": "move", "start_time": "09:07"},
            {"type": "resize", "end_time": "10:13"},
        ],
    )
    def test_rejects_non_five_minute_action_times(
        self, auth_client, today_schedule, monkeypatch, action
    ):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Gym",
            start_time="09:00",
            end_time="10:00",
            category="health",
        )
        parsed_action = {**action, "task_id": block.id}
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", [parsed_action], "Changed", None),
        )
        resp = _post(auth_client, {"messages": [_user_turn("change gym")]})
        assert resp.status_code == 200
        assert resp.json()["applied"] is False
        assert resp.json()["ask"]

    def test_log_truncates_oversized_response(self, auth_client, today_schedule, monkeypatch):
        _patch_run_chat(
            monkeypatch,
            AIParseError("too much", raw_response_text="A" * 50_000),
        )
        resp = _post(auth_client, {"messages": [_user_turn("do it")]})
        assert resp.status_code == 502
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert len(interaction.ai_response) == 10_000
        assert '"raw": "AAAA' in interaction.ai_response

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
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                "{}",
                [{"type": "move", "task_id": block.id, "start_time": "23:00"}],
                "Moved",
                None,
            ),
        )
        resp = _post(auth_client, {"messages": [_user_turn("move gym")]})
        assert resp.status_code == 200
        assert resp.json()["applied"] is False
        assert resp.json()["ask"]

    @pytest.mark.parametrize(
        "start_time,end_time,expected_status",
        [
            ("05:30", "06:00", 200),
            ("22:30", "23:30", 200),
            ("06:00", "23:00", 200),
        ],
    )
    def test_add_day_window(
        self,
        auth_client,
        user,
        today_schedule,
        monkeypatch,
        start_time,
        end_time,
        expected_status,
    ):
        # Feature 0053: make the DEFAULT window explicit. Behaviour is identical
        # to the pre-0053 hardcoded 06:00–23:00 (the default seeded window), but
        # this now proves the boundary is window-driven, not a constant.
        _set_window(user, datetime.time(6, 0), datetime.time(23, 0))
        action = {
            "type": "add",
            "title": "Boundary block",
            "start_time": start_time,
            "end_time": end_time,
            "category": "work",
        }
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", [action], "Added", None),
        )
        resp = _post(auth_client, {"messages": [_user_turn("add block")]})
        assert resp.status_code == expected_status

    def test_resize_rejected_after_day_end(self, auth_client, user, today_schedule, monkeypatch):
        # Feature 0053: default window made explicit.
        _set_window(user, datetime.time(6, 0), datetime.time(23, 0))
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Work",
            start_time="22:00",
            end_time="22:30",
            category="work",
        )
        action = {
            "type": "resize",
            "task_id": block.id,
            "end_time": "23:30",
        }
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", [action], "Extended", None),
        )
        resp = _post(auth_client, {"messages": [_user_turn("extend work")]})
        assert resp.status_code == 200
        assert resp.json()["applied"] is True
        block.refresh_from_db()
        assert block.end_time.strftime("%H:%M") == "23:00"

    def test_locks_schedule_row(self, auth_client, today_schedule, monkeypatch):
        action = {
            "type": "add",
            "title": "Standup",
            "start_time": "10:00",
            "end_time": "10:15",
            "category": "work",
        }
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", [action], "Added", None),
        )
        original = Schedule.objects.select_for_update
        called = {"value": False}

        def _spy(*args, **kwargs):
            called["value"] = True
            return original(*args, **kwargs)

        monkeypatch.setattr(Schedule.objects, "select_for_update", _spy, raising=True)
        resp = _post(auth_client, {"messages": [_user_turn("add standup")]})
        assert resp.status_code == 200
        assert called["value"]

    def test_multiple_creates_receive_distinct_sort_orders(
        self, auth_client, today_schedule, monkeypatch
    ):
        actions = [
            {
                "type": "add",
                "title": title,
                "start_time": start,
                "end_time": end,
                "category": "work",
            }
            for title, start, end in (
                ("First", "09:00", "09:30"),
                ("Second", "10:00", "10:30"),
            )
        ]
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", actions, "Added two", None),
        )
        resp = _post(auth_client, {"messages": [_user_turn("add two")]})
        assert resp.status_code == 200
        orders = list(
            TimeBlock.objects.filter(schedule=today_schedule)
            .order_by("sort_order")
            .values_list("sort_order", flat=True)
        )
        assert orders == [0, 1]

    def test_persist_validation_error_rolls_back_with_action_index(
        self, auth_client, today_schedule, monkeypatch
    ):
        from django.core.exceptions import ValidationError

        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Keep",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )
        actions = [
            {"type": "remove", "task_id": block.id},
            {
                "type": "add",
                "title": "Bad",
                "start_time": "11:00",
                "end_time": "11:30",
                "category": "work",
            },
        ]
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", actions, "Replace", None),
        )
        original_full_clean = TimeBlock.full_clean

        def _failing_full_clean(self, *args, **kwargs):
            if self.title == "Bad":
                raise ValidationError({"title": "forced failure"})
            return original_full_clean(self, *args, **kwargs)

        monkeypatch.setattr(TimeBlock, "full_clean", _failing_full_clean)
        resp = _post(auth_client, {"messages": [_user_turn("replace block")]})
        assert resp.status_code == 400
        assert resp.json()["errors"]["action_index"] == 1
        assert TimeBlock.objects.filter(pk=block.pk).exists()
        assert not TimeBlock.objects.filter(title="Bad").exists()

    def test_mark_active_failure_rolls_back_diff(self, auth_client, today_schedule, monkeypatch):
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Gym",
            start_time="09:00",
            end_time="10:00",
            category="health",
        )
        action = {
            "type": "move",
            "task_id": block.id,
            "start_time": "11:00",
        }
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", [action], "Moved", None),
        )

        def _boom(self):
            raise RuntimeError("status transition failed")

        monkeypatch.setattr(Schedule, "mark_active_on_edit", _boom)
        with pytest.raises(RuntimeError, match="status transition failed"):
            _post(auth_client, {"messages": [_user_turn("move gym")]})
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "09:00"
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert interaction.success is False

    def test_reviewed_schedule_transitions_to_active(self, auth_client, user, monkeypatch):
        schedule = Schedule.objects.create(
            user=user,
            date="2026-04-18",
            status=Schedule.Status.REVIEWED,
        )
        action = {
            "type": "add",
            "title": "Standup",
            "start_time": "10:00",
            "end_time": "10:15",
            "category": "work",
        }
        _patch_run_chat(
            monkeypatch,
            AIChatResult("{}", [action], "Added", None),
        )
        resp = _post(auth_client, {"messages": [_user_turn("add standup")]})
        assert resp.status_code == 200
        schedule.refresh_from_db()
        assert schedule.status == Schedule.Status.ACTIVE

    @pytest.mark.django_db
    def test_chat_happy_path_with_active_rule_and_nonempty_actions(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        Rule.objects.create(user=user, text="Prefer 25m pomodoros", priority=10, is_active=True)
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Focus",
            start_time="09:00",
            end_time="10:00",
            category="work",
        )

        async def _run(messages, schedule, blocks, rules, now):
            assert all(hasattr(r, "id") for r in rules)
            return AIChatResult(
                raw_response_text="{}",
                parsed_actions=[{"type": "move", "task_id": block.id, "start_time": "11:00"}],
                explanation="Moved",
                ask=None,
            )

        monkeypatch.setattr("ai.views.run_chat", _run)
        resp = _post(
            auth_client,
            {"messages": [_user_turn("move focus later")]},
        )
        assert resp.status_code == 200
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "11:00"
        interaction = AIInteraction.objects.get(schedule=today_schedule)
        assert interaction.success is True


@pytest.mark.django_db
class TestChatNonDefaultDayWindow:
    """Feature 0053: the chat apply path resolves the per-user window under the
    apply lock (``_apply_actions_sync`` → ``get_schedule_window`` →
    ``plan_mutations(day_start=…, day_end=…)``). The planner REJECTS (never
    clamps) out-of-window actions, and the rejection error names the *user's*
    bound, not the stale default 23:00.
    """

    def test_add_rejected_under_narrowed_window_names_narrowed_bound(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        # 22:00–22:30 is inside the default 06:00–23:00 but outside a narrowed
        # 08:00–21:00 window → rejected, and the detail names 21:00 not 23:00.
        _set_window(user, datetime.time(8, 0), datetime.time(21, 0))
        action = {
            "type": "add",
            "title": "Late block",
            "start_time": "22:00",
            "end_time": "22:30",
            "category": "work",
        }
        _patch_run_chat(monkeypatch, AIChatResult("{}", [action], "Added", None))
        resp = _post(auth_client, {"messages": [_user_turn("add late block")]})
        assert resp.status_code == 200
        assert resp.json()["applied"] is False
        assert resp.json()["ask"]
        assert TimeBlock.objects.filter(schedule=today_schedule).count() == 0

    def test_add_accepted_under_widened_window(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        # An add ending 23:30 is outside the default 23:00 upper bound but inside
        # a widened 06:00–23:55 window → accepted. 23:55 (not 23:59) is
        # 5-minute-valid, the only kind ``validate_window`` accepts.
        _set_window(user, datetime.time(6, 0), datetime.time(23, 55))
        action = {
            "type": "add",
            "title": "Evening",
            "start_time": "23:00",
            "end_time": "23:30",
            "category": "work",
        }
        _patch_run_chat(monkeypatch, AIChatResult("{}", [action], "Added", None))
        resp = _post(auth_client, {"messages": [_user_turn("add evening")]})
        assert resp.status_code == 200, resp.content
        blocks = list(TimeBlock.objects.filter(schedule=today_schedule))
        assert len(blocks) == 1
        assert blocks[0].start_time.strftime("%H:%M") == "23:00"
        assert blocks[0].end_time.strftime("%H:%M") == "23:30"

    def test_resize_supplied_start_past_day_end_is_rejected(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        # SYMMETRIC-bound hole (feature 0053). The stored block's inherited end
        # 23:50 is legacy-outside the default window; a supplied start of 23:35
        # is PAST day_end. The ``start <= day_end`` half must reject it — a naive
        # ``start < day_start`` check would let 23:35 through since it's after
        # 06:00. Uses the default 06:00–23:00 window.
        _set_window(user, datetime.time(6, 0), datetime.time(23, 0))
        block = TimeBlock.objects.create(
            schedule=today_schedule,
            title="Legacy late",
            start_time="23:30",
            end_time="23:50",
            category="work",
        )
        action = {"type": "resize", "task_id": block.id, "start_time": "23:35"}
        _patch_run_chat(monkeypatch, AIChatResult("{}", [action], "Resized", None))
        resp = _post(auth_client, {"messages": [_user_turn("start it at 23:35")]})
        assert resp.status_code == 200
        assert resp.json()["applied"] is False
        assert resp.json()["ask"]
        # Not silently accepted — the stored times are unchanged.
        block.refresh_from_db()
        assert block.start_time.strftime("%H:%M") == "23:30"

    def test_narrowed_window_does_not_affect_other_user(
        self, auth_client, user, today_schedule, monkeypatch
    ):
        # Multi-user isolation: user A's narrowed window must not gate the
        # apply, which is keyed off the *authenticated* user's window. Here the
        # authenticated ``user`` keeps the default window while another user has
        # a narrow one — the 22:00 add still succeeds for ``user``.
        other = User.objects.create_user(username="narrow-other", password="x")
        _set_window(other, datetime.time(8, 0), datetime.time(21, 0))
        _set_window(user, datetime.time(6, 0), datetime.time(23, 0))
        action = {
            "type": "add",
            "title": "Evening",
            "start_time": "22:00",
            "end_time": "22:30",
            "category": "work",
        }
        _patch_run_chat(monkeypatch, AIChatResult("{}", [action], "Added", None))
        resp = _post(auth_client, {"messages": [_user_turn("add evening")]})
        assert resp.status_code == 200, resp.content
        assert TimeBlock.objects.filter(schedule=today_schedule).count() == 1


@pytest.mark.django_db
def test_chat_partially_applies_metadata_and_returns_one_resolution_ask(
    auth_client, today_schedule, monkeypatch
):
    target = TimeBlock.objects.create(
        schedule=today_schedule, title="Old", start_time="09:00", end_time="10:00", category="work"
    )
    TimeBlock.objects.create(
        schedule=today_schedule, title="Busy", start_time="10:00", end_time="11:00", category="work"
    )
    _patch_run_chat(
        monkeypatch,
        AIChatResult(
            "{}",
            [
                {
                    "type": "update",
                    "task_id": target.id,
                    "title": "Renamed",
                    "category": "health",
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "direction": "later",
                }
            ],
            "Updated",
            None,
        ),
    )
    response = _post(auth_client, {"messages": [_user_turn("rename and move it")]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["applied"] is True and payload["partial"] is True and payload["ask"]
    # FIX-4: the ask names the block by its NEW (post-rename) title, locking the
    # FIX-2 stale-pre-rename-title regression.
    assert "Renamed" in payload["ask"]
    assert payload["outcomes"][0]["status"] == "partial"
    target.refresh_from_db()
    assert target.title == "Renamed" and target.category == "health"
    assert target.start_time.strftime("%H:%M") == "09:00"
    interaction = AIInteraction.objects.get(schedule=today_schedule)
    assert interaction.success is True and interaction.outcomes_json == payload["outcomes"]


@pytest.mark.django_db
def test_chat_out_of_window_exact_move_yields_window_ask_not_direction(
    auth_client, today_schedule, monkeypatch
):
    # FIX-1: an out-of-window exact move must never call find_slot (which for
    # direction="exact" returns direction_required and would emit the
    # "earlier or later?" ask). The user must see the window-specific message
    # and the outcome must carry reason_code "out_of_window" with no suggestion.
    target = TimeBlock.objects.create(
        schedule=today_schedule,
        title="Focus",
        start_time="09:00",
        end_time="10:00",
        category="work",
    )
    _patch_run_chat(
        monkeypatch,
        AIChatResult(
            "{}",
            [
                {
                    "type": "update",
                    "task_id": target.id,
                    "start_time": "23:30",
                    "end_time": "23:59",
                }
            ],
            "Moved",
            None,
        ),
    )
    response = _post(auth_client, {"messages": [_user_turn("move it to 23:30")]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ask"] == (
        "That time is outside your schedule window. Please give a time within your day."
    )
    assert "earlier or later" not in payload["ask"]
    outcome = payload["outcomes"][0]
    assert outcome["reason_code"] == "out_of_window"
    assert outcome["suggestion"] is None
    target.refresh_from_db()
    assert target.start_time.strftime("%H:%M") == "09:00"


@pytest.mark.django_db
def test_chat_exact_conflict_then_direction_yields_concrete_suggestion(
    auth_client, today_schedule, monkeypatch
):
    # FIX-4: the primary conflict flow across two turns.
    #   Turn 1 — an EXACT move that overlaps an existing block, no direction:
    #     the outcome's suggestion is direction_required (no concrete slot) and
    #     the ask is the "earlier or later?" question.
    #   Turn 2 — the same block re-emitted with direction="later": the outcome's
    #     suggestion is now a concrete start/end and the ask proposes it.
    target = TimeBlock.objects.create(
        schedule=today_schedule,
        title="Focus",
        start_time="09:00",
        end_time="10:00",
        category="work",
    )
    TimeBlock.objects.create(
        schedule=today_schedule,
        title="Busy",
        start_time="10:00",
        end_time="11:00",
        category="work",
    )

    # --- Turn 1: exact move into the occupied 10:00–11:00 slot, no direction ---
    _patch_run_chat(
        monkeypatch,
        AIChatResult(
            "{}",
            [
                {
                    "type": "update",
                    "task_id": target.id,
                    "start_time": "10:00",
                    "end_time": "11:00",
                }
            ],
            "Moved",
            None,
        ),
    )
    resp1 = _post(auth_client, {"messages": [_user_turn("move focus to 10:00")]})
    assert resp1.status_code == 200, resp1.content
    payload1 = resp1.json()
    assert payload1["applied"] is False
    suggestion1 = payload1["outcomes"][0]["suggestion"]
    assert suggestion1 == {"direction_required": True}
    assert payload1["ask"] == (
        "That time conflicts. Should I look for an earlier or later slot?"
    )
    # The exact-conflict turn must not have moved the block.
    target.refresh_from_db()
    assert target.start_time.strftime("%H:%M") == "09:00"

    # --- Turn 2: re-emit the same interval carrying direction="later" ---
    _patch_run_chat(
        monkeypatch,
        AIChatResult(
            "{}",
            [
                {
                    "type": "update",
                    "task_id": target.id,
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "direction": "later",
                }
            ],
            "Moved",
            None,
        ),
    )
    resp2 = _post(
        auth_client,
        {
            "messages": [
                _user_turn("move focus to 10:00"),
                _assistant_turn("earlier or later?"),
                _user_turn("later"),
            ]
        },
    )
    assert resp2.status_code == 200, resp2.content
    payload2 = resp2.json()
    suggestion2 = payload2["outcomes"][0]["suggestion"]
    # Now a concrete slot, not the direction_required sentinel.
    assert suggestion2 is not None
    assert not suggestion2.get("direction_required")
    assert "start_time" in suggestion2 and "end_time" in suggestion2
    assert suggestion2["direction"] == "later"
    # The free slot after Busy (10:00–11:00) is 11:00–12:00.
    assert suggestion2["start_time"] == "11:00"
    assert suggestion2["end_time"] == "12:00"
    assert payload2["ask"] == "Focus conflicts at that time. Move it to 11:00–12:00?"


class TestResolutionAskPrecedence:
    """FIX-D: ``_build_resolution_ask`` resolves by fixed precedence across ALL
    skipped outcomes (order-invariant) and names both blocks of an
    ``unresolved_conflict``."""

    @staticmethod
    def _skipped_add(action_index: int) -> ActionOutcome:
        return ActionOutcome(
            action_index=action_index,
            task_id=None,
            status="skipped",
            skipped_fields=("title", "category", "start_time", "end_time"),
            reason_code="out_of_window",
        )

    @staticmethod
    def _unresolved_conflict(action_index: int, task_id: int, other: int) -> ActionOutcome:
        return ActionOutcome(
            action_index=action_index,
            task_id=task_id,
            status="skipped",
            skipped_fields=("start_time", "end_time"),
            reason_code="unresolved_conflict",
            conflicting_task_ids=(other,),
        )

    def test_unresolved_conflict_wins_over_skipped_add_both_orders(self):
        block_titles = {10: "Focus", 20: "Standup"}
        create_titles = {0: "New meeting"}
        add = self._skipped_add(0)
        conflict = self._unresolved_conflict(1, 10, 20)

        expected = "'Focus' and 'Standup' can't both move to that time. Which should move?"
        ask_a = _build_resolution_ask((add, conflict), block_titles, create_titles)
        ask_b = _build_resolution_ask((conflict, add), block_titles, create_titles)
        assert ask_a == expected
        assert ask_b == expected  # order-invariant

    def test_unresolved_conflict_names_both_blocks(self):
        block_titles = {10: "Focus", 20: "Standup"}
        conflict = self._unresolved_conflict(0, 10, 20)
        ask = _build_resolution_ask((conflict,), block_titles, {})
        assert "'Focus'" in ask and "'Standup'" in ask

    def test_out_of_window_move_yields_window_specific_ask(self):
        # An existing-block move skipped purely for falling outside the day
        # window (no suggestion / direction / conflict) gets the specific
        # window message, not the generic "not valid or available" tail.
        block_titles = {10: "Focus"}
        out_of_window = ActionOutcome(
            action_index=0,
            task_id=10,
            status="skipped",
            skipped_fields=("start_time", "end_time"),
            reason_code="out_of_window",
        )
        ask = _build_resolution_ask((out_of_window,), block_titles, {})
        assert ask == (
            "That time is outside your schedule window. "
            "Please give a time within your day."
        )
