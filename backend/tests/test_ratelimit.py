"""Regression tests for the shared fixed-window rate limiter."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock, local
from types import SimpleNamespace

from django.core.cache import cache
from schedules.ratelimit import (
    _MAX_RESEED_ATTEMPTS,
    RATE_LIMIT_WINDOW_SECONDS,
    category_mutation_rate_limit_key,
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
    assert RATE_LIMIT_WINDOW_SECONDS == 3600


def test_consume_rate_limit_recovers_from_expiry_between_add_and_incr(monkeypatch):
    key = "connect_rl:test:expired"
    cache_key = cache.make_key(key)
    assert consume_rate_limit(key, limit=2)
    real_add = cache.add
    expired = False

    def expire_after_failed_add(*args, **kwargs):
        nonlocal expired
        result = real_add(*args, **kwargs)
        if not result and not expired:
            expired = True
            cache._expire_info[cache_key] = time.time() - 1
        return result

    monkeypatch.setattr("schedules.ratelimit.cache.add", expire_after_failed_add)

    assert consume_rate_limit(key, limit=2)
    assert cache.get(key) == 1
    assert cache._expire_info[cache_key] - time.time() > RATE_LIMIT_WINDOW_SECONDS / 2


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
    assert ttl_remaining > RATE_LIMIT_WINDOW_SECONDS / 2


def test_consume_rate_limit_contention_single_add_winner_others_increment(
    monkeypatch,
):
    key = "connect_rl:test:6"
    callers = 8
    limit = 3
    assert consume_rate_limit(key, limit=limit)
    real_add = cache.add
    real_incr = cache.incr
    real_delete = cache.delete
    thread_state = local()
    record_lock = Lock()
    expired_barrier = Barrier(callers, action=lambda: real_delete(key), timeout=5)
    reseed_results = []

    def race_add(*args, **kwargs):
        if not getattr(thread_state, "started", False):
            thread_state.started = True
            # Every caller observes the old window before it expires.
            result = real_add(*args, **kwargs)
            assert result is False
            expired_barrier.wait()
            return result
        result = real_add(*args, **kwargs)
        with record_lock:
            reseed_results.append(result)
        return result

    def race_incr(incr_key):
        if not getattr(thread_state, "recovering", False):
            thread_state.recovering = True
            # Each caller's first increment encounters the expired window.
            raise ValueError("key expired")
        return real_incr(incr_key)

    monkeypatch.setattr(
        "schedules.ratelimit.cache", SimpleNamespace(add=race_add, incr=race_incr)
    )

    with ThreadPoolExecutor(max_workers=callers) as pool:
        results = list(pool.map(lambda _: consume_rate_limit(key, limit=limit), range(callers)))

    assert sum(reseed_results) == 1
    assert sum(results) == limit
    assert cache.get(key) == callers


def test_consume_rate_limit_repeated_eviction_fails_closed(monkeypatch, caplog):
    key = "connect_rl:test:7"
    add_calls = 0
    incr_calls = 0

    def always_false(*_args, **_kwargs):
        nonlocal add_calls
        add_calls += 1
        return False

    def always_raise(_key):
        nonlocal incr_calls
        incr_calls += 1
        raise ValueError("key repeatedly evicted")

    monkeypatch.setattr("schedules.ratelimit.cache.add", always_false)
    monkeypatch.setattr("schedules.ratelimit.cache.incr", always_raise)

    with caplog.at_level(logging.WARNING, logger="schedules.ratelimit"):
        assert consume_rate_limit(key, limit=2) is False

    # The full retry budget must be consumed before failing closed: one initial
    # attempt outside the loop plus _MAX_RESEED_ATTEMPTS inside it. Guards
    # against a short-circuit regression that fails closed after a single retry.
    assert add_calls == _MAX_RESEED_ATTEMPTS + 1
    assert incr_calls == _MAX_RESEED_ATTEMPTS + 1

    # The reseed warning must fire once per recovery entry, not once per retry
    # attempt — guards against a regression that moves it inside the loop.
    reseed_warnings = [
        record
        for record in caplog.records
        if "evicted mid-window" in record.getMessage()
    ]
    assert len(reseed_warnings) == 1


def test_connect_rate_limit_key_shape():
    assert connect_rate_limit_key("caldav", 42) == "connect_rl:caldav:42"


def test_category_mutation_rate_limit_key_shape():
    assert category_mutation_rate_limit_key(42) == "category_mutation_rl:42"


def test_rate_limited_response_envelope_and_retry_after():
    response = rate_limited_response()

    assert response.status_code == 429
    assert response["Retry-After"] == "3600"
    payload = json.loads(response.content)
    assert payload["errors"]["detail"] == "Rate limit exceeded. Try again later."
