"""Unit tests for the synchronous shared connect rate limiter."""

import json
import time

from django.core.cache import cache
from schedules.ratelimit import (
    CONNECT_RATE_LIMIT_WINDOW_SECONDS,
    connect_rate_limit_key,
    consume_rate_limit,
    rate_limited_response,
)


def test_consume_rate_limit_allows_within_budget_then_blocks():
    key = "connect_rl:test:1"

    assert consume_rate_limit(key, limit=2) is True
    assert cache.get(key) == 1
    assert consume_rate_limit(key, limit=2) is True
    assert cache.get(key) == 2
    assert consume_rate_limit(key, limit=2) is False
    assert cache.get(key) == 3


def test_consume_rate_limit_reseeds_via_add_after_genuine_eviction(monkeypatch):
    key = "connect_rl:test:2"
    assert consume_rate_limit(key, limit=2) is True
    real_incr = cache.incr
    evicted = False

    def evict_once_then_raise(incr_key):
        nonlocal evicted
        if not evicted:
            evicted = True
            cache.delete(incr_key)
            raise ValueError("key evicted")
        return real_incr(incr_key)

    monkeypatch.setattr("schedules.ratelimit.cache.incr", evict_once_then_raise)

    # The first incr both evicts the key and raises, modelling a genuine
    # mid-window eviction: recovery add then succeeds against the missing key
    # and reseeds a fresh window. (An always-raising wrapper that left the key
    # present would instead fail closed under the bounded-retry algorithm.)
    assert consume_rate_limit(key, limit=2) is True
    assert cache.get(key) == 1


def test_consume_rate_limit_preserves_window_ttl():
    key = "connect_rl:test:3"
    cache_key = cache.make_key(key)

    # `_expire_info` is a LocMem-only private test seam (the unit suite
    # pins CACHES to LocMem); mirrors test_ai_apply.py::
    # test_increment_preserves_window_ttl. It reads the absolute expiry
    # deadline directly because LocMem exposes no public TTL accessor.
    assert consume_rate_limit(key, limit=2) is True
    expiry_after_first_call = cache._expire_info[cache_key]

    assert consume_rate_limit(key, limit=2) is True
    expiry_after_second_call = cache._expire_info[cache_key]

    assert expiry_after_second_call == expiry_after_first_call
    assert expiry_after_first_call > 0
    assert CONNECT_RATE_LIMIT_WINDOW_SECONDS == 3600


def test_consume_rate_limit_race_recovery_callers_share_one_window(monkeypatch):
    key = "connect_rl:test:4"
    limit = 3
    real_incr = cache.incr
    pending_raise = False

    def raise_once_per_armed_call(incr_key):
        nonlocal pending_raise
        if pending_raise:
            pending_raise = False
            raise ValueError("simulated eviction race")
        return real_incr(incr_key)

    monkeypatch.setattr("schedules.ratelimit.cache.incr", raise_once_per_armed_call)

    results = []
    for _ in range(6):
        pending_raise = True
        results.append(consume_rate_limit(key, limit=limit))

    assert results == [True, True, True, False, False, False]
    assert sum(results) == limit
    assert cache.get(key) == 6


def test_consume_rate_limit_reseeded_window_has_full_ttl(monkeypatch):
    key = "connect_rl:test:5"
    cache_key = cache.make_key(key)
    assert consume_rate_limit(key, limit=2) is True
    real_incr = cache.incr
    evicted = False

    def evict_once_then_raise(incr_key):
        nonlocal evicted
        if not evicted:
            evicted = True
            cache.delete(incr_key)
            raise ValueError("key evicted")
        return real_incr(incr_key)

    monkeypatch.setattr("schedules.ratelimit.cache.incr", evict_once_then_raise)

    assert consume_rate_limit(key, limit=2) is True
    ttl_remaining = cache._expire_info[cache_key] - time.time()
    assert ttl_remaining > CONNECT_RATE_LIMIT_WINDOW_SECONDS / 2


def test_consume_rate_limit_contention_single_add_winner_others_increment(
    monkeypatch,
):
    key = "connect_rl:test:6"
    assert consume_rate_limit(key, limit=5) is True
    real_add = cache.add
    real_incr = cache.incr
    add_results = []
    caller = 0
    pending_raise = False

    def record_add(*args, **kwargs):
        result = real_add(*args, **kwargs)
        add_results.append(result)
        return result

    def race_incr(incr_key):
        nonlocal pending_raise
        if pending_raise:
            pending_raise = False
            if caller == 1:
                cache.delete(incr_key)
            raise ValueError("simulated eviction race")
        return real_incr(incr_key)

    monkeypatch.setattr("schedules.ratelimit.cache.add", record_add)
    monkeypatch.setattr("schedules.ratelimit.cache.incr", race_incr)

    results = []
    for caller in range(1, 5):
        pending_raise = True
        results.append(consume_rate_limit(key, limit=5))

    assert sum(add_results) == 1
    assert results == [True, True, True, True]
    assert cache.get(key) == 4


def test_consume_rate_limit_repeated_eviction_fails_closed(monkeypatch):
    key = "connect_rl:test:7"

    def always_raise(_key):
        raise ValueError("key repeatedly evicted")

    monkeypatch.setattr("schedules.ratelimit.cache.add", lambda *_args, **_kwargs: False)
    monkeypatch.setattr("schedules.ratelimit.cache.incr", always_raise)

    assert consume_rate_limit(key, limit=2) is False


def test_connect_rate_limit_key_shape():
    assert connect_rate_limit_key("caldav", 42) == "connect_rl:caldav:42"


def test_rate_limited_response_envelope_and_retry_after():
    response = rate_limited_response()

    assert response.status_code == 429
    assert response["Retry-After"] == "3600"
    payload = json.loads(response.content)
    assert payload["errors"]["detail"] == "Rate limit exceeded. Try again later."
