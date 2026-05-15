"""Integration tests for the ``ai_chat`` multi-turn view (feature 0007).

Each test monkeypatches ``ai.service.run_chat`` with a canned result or
error so no network call is made. The view's validation order, audit
logging shape, rate-limit independence, and untrusted-transcript
handling are all exercised against real DB.
"""
import hashlib
import json

import pytest
from ai.models import AIInteraction
from ai.service import (
    AIChatResult,
    AIInvalidInputError,
    AIParseError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
)
from django.core.cache import cache
from schedules.models import Schedule, TimeBlock

URL = "/api/ai/schedules/2026-04-18/chat/"


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

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "body",
        [
            "[]",
            '"x"',
            "123",
            "null",
            "true",
        ],
    )
    def test_non_object_json_root_returns_400(self, auth_client, body):
        """Lock the contract that malformed bodies always return 4xx, never 5xx.

        Valid JSON with a non-dict root (``[]``, ``"x"``, ``123``,
        ``null``, ``true``) parses cleanly via ``json.loads`` but would
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
            json.dumps(
                {"messages": [_user_turn("x" * 2_000_000)]}
            ),
            content_type="application/json",
        )
        assert resp.status_code == 413

    @pytest.mark.django_db
    def test_invalid_body_does_not_create_schedule(self, user, auth_client):
        # No Schedule row exists for this user/date yet.
        assert (
            Schedule.objects.filter(
                user=user, date="2026-04-18"
            ).count()
            == 0
        )
        resp = _post(auth_client, {"messages": [_user_turn("")]})
        assert resp.status_code == 400
        # Validation runs BEFORE get_or_create — no row should be persisted.
        assert (
            Schedule.objects.filter(
                user=user, date="2026-04-18"
            ).count()
            == 0
        )

    @pytest.mark.django_db
    def test_validation_failures_do_not_consume_rate_limit(
        self, user, auth_client, settings
    ):
        settings.LLM_CHAT_RATE_LIMIT_PER_HOUR = 5
        # Five malformed bodies in a row — none should burn the budget.
        for _ in range(5):
            resp = _post(auth_client, {"messages": []})
            assert resp.status_code == 400
        # Counter must still be at zero.
        assert cache.get(f"ai_chat_rl:{user.id}") in (None, 0)


class TestClarifyingQuestion:
    @pytest.mark.django_db
    def test_returns_ask_without_mutating(
        self, user, auth_client, today_schedule, monkeypatch
    ):
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text='{"actions":[],"explanation":"need info","ask":"when?"}',
                parsed_actions=[],
                explanation="need info",
                ask="when?",
            ),
        )
        resp = _post(
            auth_client, {"messages": [_user_turn("add gym")]}
        )
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
    def test_apply_actions_creates_blocks(
        self, user, auth_client, today_schedule, monkeypatch
    ):
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
    def test_chitchat_no_op(
        self, user, auth_client, today_schedule, monkeypatch
    ):
        _patch_run_chat(
            monkeypatch,
            AIChatResult(
                raw_response_text='{"actions":[],"explanation":"you are welcome","ask":null}',
                parsed_actions=[],
                explanation="you are welcome",
                ask=None,
            ),
        )
        resp = _post(
            auth_client, {"messages": [_user_turn("thanks!")]}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied"] is False
        assert data["ask"] is None
        # Status stays as default (draft).
        today_schedule.refresh_from_db()
        assert today_schedule.status == "draft"


class TestRateLimit:
    @pytest.mark.django_db
    def test_chat_bucket_independent_of_command(
        self, user, auth_client, monkeypatch, settings
    ):
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
        # Command bucket is still untouched — counter key never set.
        assert cache.get(f"ai_cmd_rl:{user.id}") in (None, 0)


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
        payload = json.loads(row.ai_response)
        expected = hashlib.sha256(
            json.dumps(messages, sort_keys=True, ensure_ascii=False).encode(
                "utf-8"
            )
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
            json.dumps(messages, sort_keys=True, ensure_ascii=False).encode(
                "utf-8"
            )
        ).hexdigest()
        assert payload["transcript_sha256"] == expected_hash
        assert payload["turn_count"] == 1
        assert payload["error_class"] == type(exc).__name__
        if isinstance(exc, AIParseError):
            assert payload["raw"] == "not-json"
        else:
            assert payload["raw"] == str(exc)
