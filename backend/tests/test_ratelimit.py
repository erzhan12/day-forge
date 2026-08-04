"""Unit tests for the synchronous shared connect rate limiter."""

from django.core.cache import cache
from schedules.ratelimit import (
    CONNECT_RATE_LIMIT_WINDOW_SECONDS,
    consume_rate_limit,
)


def test_consume_rate_limit_allows_within_budget_then_blocks():
    key = "connect_rl:test:1"

    assert consume_rate_limit(key, limit=2) is True
    assert cache.get(key) == 1
    assert consume_rate_limit(key, limit=2) is True
    assert cache.get(key) == 2
    assert consume_rate_limit(key, limit=2) is False
    assert cache.get(key) == 3


def test_consume_rate_limit_reseeds_on_incr_value_error(monkeypatch):
    key = "connect_rl:test:2"
    assert consume_rate_limit(key, limit=2) is True

    def raise_value_error(_key):
        raise ValueError("key missing")

    monkeypatch.setattr("schedules.ratelimit.cache.incr", raise_value_error)

    assert consume_rate_limit(key, limit=2) is True
    assert cache.get(key) == 1


def test_consume_rate_limit_preserves_window_ttl():
    key = "connect_rl:test:3"
    cache_key = cache.make_key(key)

    assert consume_rate_limit(key, limit=2) is True
    expiry_after_first_call = cache._expire_info[cache_key]

    assert consume_rate_limit(key, limit=2) is True
    expiry_after_second_call = cache._expire_info[cache_key]

    assert expiry_after_second_call == expiry_after_first_call
    assert expiry_after_first_call > 0
    assert CONNECT_RATE_LIMIT_WINDOW_SECONDS == 3600
