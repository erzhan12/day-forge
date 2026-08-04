"""Shared contract for the per-provider connect-endpoint rate limiter.

Feature 0036 added an identical per-user fixed-window rate limit to the
three credential-verifying connect POST handlers (CalDAV, Todoist,
Habitica). Their view-level tests were byte-for-byte parallel modulo a
handful of per-provider values, so the assertions live here once and each
provider's ``test_*_sync_views.py`` subclasses ``ConnectRateLimitContract``
with its own knobs.

The base class is deliberately **not** ``Test``-prefixed so pytest does
not collect it standalone (it would fail with unset attributes); only the
provider subclasses — which set every attribute below — are collected.

Subclass contract (all required):

- ``URL`` — the connect endpoint path.
- ``SLUG`` — provider slug in the counter key ``connect_rl:<slug>:<uid>``.
- ``SETTINGS_ATTR`` — the ``*_CONNECT_RATE_LIMIT_PER_HOUR`` settings name.
- ``MOCK_TARGET`` — dotted path to the provider's ``verify_credentials``.
- ``AUTH_ERROR`` — the provider's auth-failure exception class (→ 401).
- ``valid_body`` — a dict POST body that passes payload validation.
- ``oversized_body`` — ``valid_body`` with the secret blown past the body
  cap (→ 413 before consumption).
- ``EXPECTED_VERIFY_ARGS`` — the positional args the view forwards to
  ``verify_credentials`` for ``valid_body``.
"""

from unittest.mock import patch

import pytest
from django.core.cache import cache

# Parametrize sentinel: stands in for each subclass's ``oversized_body``
# (resolved per-instance inside the test, since the decorator can't read
# ``self``). A named sentinel reads clearer than a bare ``None``.
_OVERSIZED = object()


class ConnectRateLimitContract:
    URL: str
    SLUG: str
    SETTINGS_ATTR: str
    MOCK_TARGET: str
    AUTH_ERROR: type[Exception]
    valid_body: dict
    oversized_body: dict
    EXPECTED_VERIFY_ARGS: tuple

    def _post(self, client):
        return client.post(
            self.URL, data=self.valid_body, content_type="application/json"
        )

    def _key(self, user):
        return f"connect_rl:{self.SLUG}:{user.id}"

    def test_returns_429_once_connect_budget_exceeded(self, auth_client, settings):
        setattr(settings, self.SETTINGS_ATTR, 2)
        with patch(self.MOCK_TARGET) as verify:
            assert self._post(auth_client).status_code == 200
            assert self._post(auth_client).status_code == 200
            response = self._post(auth_client)

        assert response.status_code == 429
        assert "rate limit" in response.json()["errors"]["detail"].lower()
        assert verify.call_count == 2

    def test_429_short_circuits_before_verify_credentials(self, auth_client, settings):
        setattr(settings, self.SETTINGS_ATTR, 1)
        with patch(self.MOCK_TARGET) as verify:
            assert self._post(auth_client).status_code == 200
            assert self._post(auth_client).status_code == 429

        verify.assert_called_once_with(*self.EXPECTED_VERIFY_ARGS)

    def test_counter_stored_under_expected_key(self, auth_client, user, settings):
        setattr(settings, self.SETTINGS_ATTR, 3)
        key = self._key(user)
        assert cache.get(key) is None
        with patch(self.MOCK_TARGET):
            assert self._post(auth_client).status_code == 200
            assert cache.get(key) == 1
            assert self._post(auth_client).status_code == 200
            assert cache.get(key) == 2

    def test_failed_verify_still_consumes_token(self, auth_client, user, settings):
        setattr(settings, self.SETTINGS_ATTR, 2)
        key = self._key(user)
        with patch(self.MOCK_TARGET) as verify:
            verify.side_effect = self.AUTH_ERROR("bad credentials")
            assert self._post(auth_client).status_code == 401
            assert self._post(auth_client).status_code == 401
            assert cache.get(key) == 2
            assert self._post(auth_client).status_code == 429

        assert verify.call_count == 2

    @pytest.mark.parametrize(
        "body, status",
        [({}, 400), (_OVERSIZED, 413), ("{", 400)],
    )
    def test_pre_validation_does_not_consume_token(
        self, auth_client, user, body, status
    ):
        # _OVERSIZED resolves to the provider's oversized body (→ 413); the
        # empty dict (→ 400) and malformed "{" (→ 400) are literal.
        body = self.oversized_body if body is _OVERSIZED else body
        response = auth_client.post(
            self.URL, data=body, content_type="application/json"
        )
        assert response.status_code == status
        assert cache.get(self._key(user)) is None

    def test_get_and_delete_not_rate_limited(self, auth_client, user, settings):
        setattr(settings, self.SETTINGS_ATTR, 1)
        # No account is pre-created: GET (status) returns 200 with
        # connected=False and DELETE is idempotent (200), for all three
        # providers today. A future provider whose DELETE returns 204/404
        # with no row on file must relax these assertions.
        for _ in range(3):
            assert auth_client.get(self.URL).status_code == 200
            assert auth_client.delete(self.URL).status_code == 200
        assert cache.get(self._key(user)) is None
