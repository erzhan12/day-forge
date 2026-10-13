"""Endpoint-independent regression tests for shared AI helpers."""

import json
import time

import ai.views
import pytest
from ai.service import AIChatResult
from asgiref.sync import async_to_sync, sync_to_async
from django.core.cache import cache
from schedules.models import Schedule
from schedules.ratelimit import _MAX_RESEED_ATTEMPTS, RATE_LIMIT_WINDOW_SECONDS


class TestRollbackPropagation:
    """Narrow scope: pins ONLY that ``_Rollback`` re-raises across the
    ``sync_to_async`` / ``async_to_sync`` asgiref boundary (the stale-fingerprint
    409 path, which raises before any DB write). Full ``transaction.atomic()``
    rollback of real writes is covered via the view path by
    ``test_ai_views_chat.py::test_mid_batch_failure_rolls_back`` and
    ``test_persist_validation_error_rolls_back_with_action_index``.
    """

    @pytest.mark.django_db
    def test_rollback_propagates_across_sync_to_async(self, user):
        schedule = Schedule.objects.create(user=user, date="2026-04-18")
        result = AIChatResult(
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
            ask=None,
        )

        async def _run():
            return await sync_to_async(
                ai.views._apply_actions_sync,
                thread_sensitive=True,
            )(
                schedule,
                result,
                expected_fingerprint="stale-garbage",
                expected_revision=schedule.revision,
                interaction_id=None,
            )

        with pytest.raises(ai.views._Rollback) as excinfo:
            async_to_sync(_run)()

        assert excinfo.value.response.status_code == 409
        assert json.loads(excinfo.value.response.content)["code"] == "schedule_changed"


class TestRateLimitCounter:
    def test_cache_incr_value_error_reseeds_counter(self, monkeypatch):
        key_prefix = "ai_test_rl_reseed"
        user_id = 101
        key = f"{key_prefix}:{user_id}"
        assert async_to_sync(ai.views._consume_rate_limit)(user_id, key_prefix, 10)
        real_incr = cache.incr
        evicted = False

        def evict_once_then_increment(incr_key):
            nonlocal evicted
            if not evicted:
                evicted = True
                cache.delete(incr_key)
            return real_incr(incr_key)

        monkeypatch.setattr("schedules.ratelimit.cache.incr", evict_once_then_increment)
        assert async_to_sync(ai.views._consume_rate_limit)(user_id, key_prefix, 10)
        assert cache.get(key) == 1

    def test_repeated_eviction_fails_closed_without_resetting_counter(self, monkeypatch):
        key_prefix = "ai_test_rl_exhausted"
        user_id = 103
        key = f"{key_prefix}:{user_id}"
        assert async_to_sync(ai.views._consume_rate_limit)(user_id, key_prefix, 10)
        incr_calls = []

        def always_raise(incr_key):
            incr_calls.append(incr_key)
            raise ValueError("key missing")

        monkeypatch.setattr("schedules.ratelimit.cache.incr", always_raise)

        assert not async_to_sync(ai.views._consume_rate_limit)(user_id, key_prefix, 10)
        assert incr_calls == [key] * (_MAX_RESEED_ATTEMPTS + 1)
        assert cache.get(key) == 1

    def test_counter_uses_atomic_sync_increment(self, monkeypatch):
        key_prefix = "ai_test_rl_atomic"
        user_id = 104
        real_incr = cache.incr
        incremented_keys = []

        def record_incr(key):
            incremented_keys.append(key)
            return real_incr(key)

        async def reject_async_increment(*args, **kwargs):
            pytest.fail("Async read-modify-write must not increment the rate-limit counter")

        monkeypatch.setattr("schedules.ratelimit.cache.incr", record_incr)
        monkeypatch.setattr("schedules.ratelimit.cache.aincr", reject_async_increment)

        assert async_to_sync(ai.views._consume_rate_limit)(user_id, key_prefix, 1)
        assert not async_to_sync(ai.views._consume_rate_limit)(user_id, key_prefix, 1)
        assert incremented_keys == [f"{key_prefix}:{user_id}"]

    def test_increment_preserves_window_ttl(self):
        key_prefix = "ai_test_rl_ttl"
        user_id = 102
        key = cache.make_key(f"{key_prefix}:{user_id}")

        assert async_to_sync(ai.views._consume_rate_limit)(user_id, key_prefix, 10)
        first_expiry = cache._expire_info[key]
        assert async_to_sync(ai.views._consume_rate_limit)(user_id, key_prefix, 10)

        # ``_expire_info`` is a LocMemCache-private test seam (valid only because
        # conftest._pin_test_cache_backend pins CACHES['default'] to LocMemCache
        # for the suite); it breaks on any other backend. Mirrors the note in
        # test_ratelimit.py:42-45.
        assert cache._expire_info[key] == first_expiry
        ttl_remaining = first_expiry - time.time()
        assert ttl_remaining > RATE_LIMIT_WINDOW_SECONDS / 2
