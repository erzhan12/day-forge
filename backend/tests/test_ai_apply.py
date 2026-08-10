"""Endpoint-independent regression tests for shared AI helpers."""

import json
import time

import ai.views
import pytest
from ai.service import AICommandResult
from asgiref.sync import async_to_sync, sync_to_async
from django.core.cache import cache
from schedules.models import Schedule


class TestRollbackPropagation:
    @pytest.mark.django_db
    def test_rollback_propagates_across_sync_to_async(self, user):
        schedule = Schedule.objects.create(user=user, date="2026-04-18")
        result = AICommandResult(
            raw_response_text="{}",
            parsed_actions=[
                {
                    "type": "add",
                    "title": "Standup",
                    "start_time": "09:00",
                    "end_time": "09:30",
                    "category": "work",
                }
            ],
            explanation="x",
        )

        async def _run():
            return await sync_to_async(
                ai.views._apply_actions_sync,
                thread_sensitive=True,
            )(
                schedule,
                result,
                expected_fingerprint="stale-garbage",
                interaction_id=None,
            )

        with pytest.raises(ai.views._Rollback) as excinfo:
            async_to_sync(_run)()

        assert excinfo.value.response.status_code == 409
        assert json.loads(excinfo.value.response.content) == {
            "errors": {"detail": "schedule_changed"}
        }


class TestRateLimitCounter:
    def test_cache_incr_value_error_reseeds_counter(self, monkeypatch):
        key_prefix = "ai_test_rl_reseed"
        user_id = 101
        assert async_to_sync(ai.views._consume_rate_limit)(
            user_id, key_prefix, 10
        )

        def _raise_value_error(_key):
            raise ValueError("key missing")

        monkeypatch.setattr("ai.views.cache.incr", _raise_value_error)
        assert async_to_sync(ai.views._consume_rate_limit)(
            user_id, key_prefix, 10
        )
        assert cache.get(f"{key_prefix}:{user_id}") == 1

    def test_increment_preserves_window_ttl(self):
        key_prefix = "ai_test_rl_ttl"
        user_id = 102
        key = cache.make_key(f"{key_prefix}:{user_id}")

        assert async_to_sync(ai.views._consume_rate_limit)(
            user_id, key_prefix, 10
        )
        assert async_to_sync(ai.views._consume_rate_limit)(
            user_id, key_prefix, 10
        )

        ttl_remaining = cache._expire_info[key] - time.time()
        assert ttl_remaining > 1800
