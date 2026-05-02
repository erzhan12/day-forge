"""Unit tests for ``ai.service.run_command``.

The OpenAI SDK client is monkeypatched via ``ai.service._get_client`` — no
network calls are made.
"""
import datetime
import json
from types import SimpleNamespace

import openai
import pytest
from ai.service import (
    AIInvalidInputError,
    AIParseError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
    run_command,
)


class FakeCompletions:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if callable(self.behaviour):
            return self.behaviour()
        return self.behaviour


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, completions):
        self.chat = FakeChat(completions)


def _make_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


@pytest.fixture
def patch_client(monkeypatch):
    """Return a helper that installs a FakeClient whose completions.create
    returns the given JSON string (or raises the given exception)."""

    def _install(behaviour):
        if isinstance(behaviour, str):
            response = _make_response(behaviour)
            completions = FakeCompletions(response)
        elif isinstance(behaviour, Exception):
            def _raise():
                raise behaviour
            completions = FakeCompletions(_raise)
        else:
            completions = FakeCompletions(behaviour)
        client = FakeClient(completions)
        monkeypatch.setattr("ai.service._get_client", lambda: client)
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "test-key")
        return completions

    return _install


@pytest.fixture
def fake_schedule():
    return SimpleNamespace(date=datetime.date(2026, 4, 18))


@pytest.fixture
def now():
    return datetime.datetime(2026, 4, 18, 9, 30)


class TestInputValidation:
    def test_missing_api_key_raises_unavailable(self, monkeypatch, fake_schedule, now):
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "")
        with pytest.raises(AIUnavailableError):
            run_command("add standup", fake_schedule, [], now)

    def test_non_string_command_raises(self, monkeypatch, fake_schedule, now):
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "test")
        with pytest.raises(AIInvalidInputError):
            run_command(None, fake_schedule, [], now)  # type: ignore[arg-type]

    def test_empty_command_raises(self, monkeypatch, fake_schedule, now):
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "test")
        with pytest.raises(AIInvalidInputError):
            run_command("   ", fake_schedule, [], now)

    def test_oversized_command_raises(self, monkeypatch, fake_schedule, now):
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "test")
        monkeypatch.setattr("django.conf.settings.LLM_MAX_COMMAND_CHARS", 10)
        with pytest.raises(AIInvalidInputError):
            run_command("a" * 50, fake_schedule, [], now)


class TestProviderErrors:
    def test_timeout_maps_to_ai_timeout(self, patch_client, fake_schedule, now):
        patch_client(openai.APITimeoutError(request=None))
        with pytest.raises(AITimeoutError):
            run_command("do thing", fake_schedule, [], now)

    def test_api_error_maps_to_provider(self, patch_client, fake_schedule, now):
        patch_client(openai.APIError("boom", request=None, body=None))
        with pytest.raises(AIProviderError):
            run_command("do thing", fake_schedule, [], now)

    def test_unexpected_exception_maps_to_provider(
        self, patch_client, fake_schedule, now
    ):
        patch_client(RuntimeError("network down"))
        with pytest.raises(AIProviderError):
            run_command("do thing", fake_schedule, [], now)


class TestParsing:
    def test_invalid_json_raises_parse(self, patch_client, fake_schedule, now):
        patch_client("not-json")
        with pytest.raises(AIParseError) as exc:
            run_command("do thing", fake_schedule, [], now)
        assert exc.value.raw_response_text == "not-json"

    def test_missing_actions_envelope_raises(
        self, patch_client, fake_schedule, now
    ):
        patch_client(json.dumps({"explanation": "hi"}))
        with pytest.raises(AIParseError):
            run_command("do thing", fake_schedule, [], now)

    def test_invalid_action_shape_raises(self, patch_client, fake_schedule, now):
        patch_client(
            json.dumps({
                "actions": [{"type": "add", "title": "x"}],  # missing times
                "explanation": "x",
            })
        )
        with pytest.raises(AIParseError):
            run_command("do thing", fake_schedule, [], now)

    def test_move_without_time_field_raises(self, patch_client, fake_schedule, now):
        """A ``move`` action with only ``task_id`` is a silent no-op and
        must be rejected at the schema layer."""
        patch_client(
            json.dumps({
                "actions": [{"type": "move", "task_id": 1}],
                "explanation": "noop",
            })
        )
        with pytest.raises(AIParseError):
            run_command("do thing", fake_schedule, [], now)

    def test_resize_without_time_field_raises(self, patch_client, fake_schedule, now):
        patch_client(
            json.dumps({
                "actions": [{"type": "resize", "task_id": 1}],
                "explanation": "noop",
            })
        )
        with pytest.raises(AIParseError):
            run_command("do thing", fake_schedule, [], now)

    def test_success_returns_parsed(self, patch_client, fake_schedule, now):
        payload = {
            "actions": [
                {
                    "type": "add",
                    "title": "Standup",
                    "start_time": "10:00",
                    "end_time": "10:15",
                    "category": "work",
                }
            ],
            "explanation": "Added standup",
        }
        completions = patch_client(json.dumps(payload))
        result = run_command("add standup", fake_schedule, [], now)

        assert result.explanation == "Added standup"
        assert len(result.parsed_actions) == 1
        assert result.parsed_actions[0]["type"] == "add"

        # Prompt wiring: system + user messages were sent, JSON mode was on.
        assert len(completions.calls) == 1
        call = completions.calls[0]
        assert call["response_format"] == {"type": "json_object"}
        roles = [m["role"] for m in call["messages"]]
        assert roles == ["system", "user"]
        assert "add standup" in call["messages"][1]["content"]
