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
)
from ai.service import (
    run_command as _async_run_command,
)
from asgiref.sync import async_to_sync


def run_command(*args, **kwargs):
    """Sync wrapper around the now-async ``ai.service.run_command``.

    Lets the existing sync test bodies (and sync ORM setup) keep their
    shape; the AI service entry point is async (feature 0009).
    """
    return async_to_sync(_async_run_command)(*args, **kwargs)


class FakeCompletions:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = []

    async def create(self, **kwargs):
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


class TestClientPerLoop:
    """Regression: ``_get_client`` must NOT return a module-level
    singleton.

    Under WSGI/sync gunicorn, Django adapts each async-view invocation
    through ``asgiref.sync.async_to_sync``, which uses a fresh event
    loop per call. ``httpx.AsyncClient`` (the transport ``AsyncOpenAI``
    wraps) ties its connection pool to the loop that first opened a
    connection; a module-level singleton would survive request #1 then
    crash on request #2 with a "Future attached to a different loop"
    error from anyio.

    These tests don't make a real network call — they verify the cache
    structure by inspecting client identity per loop. The fact that
    each ``async_to_sync(...)`` produces a different loop id is what
    makes the previous singleton design unsafe; this test pins the
    fix (per-loop ``WeakKeyDictionary``) so a future refactor that
    drops it fails here, not in production.
    """

    def test_different_loops_get_different_clients(self, monkeypatch):
        import asyncio

        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "sk-test")

        from ai.service import _get_client

        async def probe():
            return _get_client()

        # ``asyncio.run`` guarantees a fresh event loop per call and
        # tears it down when the coroutine returns, so we deterministic-
        # ally exercise the multi-loop branch of the cache. (Django's
        # ``async_to_sync`` adaptation under WSGI exhibits the same
        # multi-loop pattern, but asgiref's internal loop-reuse
        # heuristics make it a flaky vehicle for a unit test.)
        client1 = asyncio.run(probe())
        client2 = asyncio.run(probe())

        # Each loop must receive its own client, NOT a shared
        # module-level singleton.
        assert client1 is not client2

    def test_same_loop_reuses_client(self, monkeypatch):
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "sk-test")

        from ai.service import _get_client

        async def probe():
            # Two calls within the SAME running loop must return the
            # same client object — connection pooling within a loop is
            # preserved.
            return _get_client(), _get_client()

        a, b = async_to_sync(probe)()
        assert a is b

    def test_init_failure_raises_provider_error(self, monkeypatch):
        """The ``except`` branch around ``AsyncOpenAI(...)`` must still
        suppress the original exception so ``LLM_API_KEY`` cannot leak
        via chained traceback frames."""
        from ai import service

        def _boom(*a, **kw):
            raise RuntimeError("init failed (key=sk-secret)")

        monkeypatch.setattr("ai.service.AsyncOpenAI", _boom)
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "sk-test")
        # Clear any cached client for the test loop so we hit the
        # constructor branch.
        service._clients_by_loop.clear()

        async def probe():
            service._get_client()

        with pytest.raises(AIProviderError) as exc:
            async_to_sync(probe)()
        # ``raise ... from None`` suppresses the chain — exc.__cause__
        # must be None so the API-key-bearing inner traceback can't
        # leak via __cause__ to logs / Sentry.
        assert exc.value.__cause__ is None
