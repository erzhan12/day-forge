"""Regression tests for the per-event-loop AI client cache."""

import asyncio

import pytest
from ai.service import AIProviderError
from asgiref.sync import async_to_sync


class TestClientPerLoop:
    def test_different_loops_get_different_clients(self, monkeypatch):
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "sk-test")

        from ai.service import _get_client

        async def probe():
            return _get_client()

        client1 = asyncio.run(probe())
        client2 = asyncio.run(probe())

        assert client1 is not client2

    def test_same_loop_reuses_client(self, monkeypatch):
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "sk-test")

        from ai.service import _get_client

        async def probe():
            return _get_client(), _get_client()

        a, b = async_to_sync(probe)()
        assert a is b

    def test_init_failure_raises_provider_error(self, monkeypatch):
        from ai import service

        def _boom(*args, **kwargs):
            raise RuntimeError("init failed (key=sk-secret)")

        monkeypatch.setattr("ai.service.AsyncOpenAI", _boom)
        monkeypatch.setattr("django.conf.settings.LLM_API_KEY", "sk-test")
        service._clients_by_loop.clear()

        async def probe():
            service._get_client()

        with pytest.raises(AIProviderError) as exc:
            async_to_sync(probe)()
        # Security invariant: client init raises `from None` so the original
        # exception (whose message/locals can hold the LLM_API_KEY) is NOT
        # chained onto __cause__ and cannot leak into Sentry/logs. If a future
        # change drops `from None`, this assertion fails — flagging a reopened
        # API-key leak path.
        assert exc.value.__cause__ is None
