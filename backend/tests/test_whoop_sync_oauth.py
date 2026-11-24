"""``whoop_sync.service`` connect-time helpers (feature 0107, step 5)."""

import datetime
import logging
import urllib.parse

import httpx
import pytest
import respx
from django.utils import timezone
from whoop_sync import service

from tests.whoop_helpers import (
    AUTH_URI,
    REDIRECT_URI,
    SCOPES,
    TOKEN_URI,
    WHOOP_SETTINGS,
    token_body,
)


@pytest.fixture(autouse=True)
def _whoop_settings(settings):
    for name, value in WHOOP_SETTINGS.items():
        setattr(settings, name, value)


class TestIsConfigured:
    def test_all_four_set(self):
        assert service.is_configured() is True

    @pytest.mark.parametrize("missing", sorted(WHOOP_SETTINGS))
    def test_any_missing(self, settings, missing):
        setattr(settings, missing, "")
        assert service.is_configured() is False


class TestBuildAuthorizationUrl:
    def test_url_carries_client_redirect_scopes_and_state(self):
        url = service.build_authorization_url("ab12cd34")
        parsed = urllib.parse.urlsplit(url)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTH_URI
        query = urllib.parse.parse_qs(parsed.query)
        assert query == {
            "response_type": ["code"],
            "client_id": ["whoop-client-id"],
            "redirect_uri": [REDIRECT_URI],
            "scope": [SCOPES],
            "state": ["ab12cd34"],
        }
        assert "whoop-client-secret" not in url

    @pytest.mark.parametrize("state", ["", "abc", "ab12cd345", "a" * 32])
    def test_state_must_be_exactly_eight_characters(self, state):
        with pytest.raises(ValueError):
            service.build_authorization_url(state)


class TestExchangeCode:
    @respx.mock
    def test_success_returns_tokens_expiry_and_scopes(self):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        before = timezone.now()
        grant = service.exchange_code("the-code")
        assert grant.access_token == "access-1"
        assert grant.refresh_token == "refresh-1"
        assert grant.scopes == SCOPES
        assert before + datetime.timedelta(seconds=3590) <= grant.expiry
        assert grant.expiry <= timezone.now() + datetime.timedelta(seconds=3600)

        request = route.calls.last.request
        form = urllib.parse.parse_qs(request.content.decode())
        assert form == {
            "grant_type": ["authorization_code"],
            "code": ["the-code"],
            "redirect_uri": [REDIRECT_URI],
            "client_id": ["whoop-client-id"],
            "client_secret": ["whoop-client-secret"],
        }
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        assert request.headers["user-agent"] == "day-forge"

    @respx.mock
    def test_missing_refresh_token_is_rejected(self):
        respx.post(TOKEN_URI).respond(200, json=token_body(refresh=None))
        with pytest.raises(service.WhoopProviderError):
            service.exchange_code("the-code")

    @pytest.mark.parametrize("status", [400, 401])
    @respx.mock
    def test_rejected_code_is_an_auth_error(self, status):
        respx.post(TOKEN_URI).respond(status, json={"error": "invalid_grant"})
        with pytest.raises(service.WhoopAuthError):
            service.exchange_code("the-code")

    @respx.mock
    def test_rate_limit(self):
        respx.post(TOKEN_URI).respond(429)
        with pytest.raises(service.WhoopRateLimitError):
            service.exchange_code("the-code")

    @pytest.mark.parametrize("status", [500, 503])
    @respx.mock
    def test_server_error_is_a_provider_error(self, status):
        respx.post(TOKEN_URI).respond(status, text="BODY_MUST_NOT_LEAK")
        with pytest.raises(service.WhoopProviderError) as excinfo:
            service.exchange_code("the-code")
        assert "BODY_MUST_NOT_LEAK" not in str(excinfo.value)

    @respx.mock
    def test_network_failure_is_a_provider_error(self):
        respx.post(TOKEN_URI).mock(side_effect=httpx.ConnectTimeout("slow"))
        with pytest.raises(service.WhoopProviderError):
            service.exchange_code("the-code")

    @pytest.mark.parametrize("body", [b"not json", b"[]", b'{"access_token": 5}'])
    @respx.mock
    def test_malformed_body_is_a_provider_error(self, body):
        respx.post(TOKEN_URI).respond(200, content=body)
        with pytest.raises(service.WhoopProviderError):
            service.exchange_code("the-code")

    @respx.mock
    def test_nothing_secret_is_logged(self, caplog):
        caplog.set_level(logging.DEBUG)
        respx.post(TOKEN_URI).respond(200, json=token_body())
        service.exchange_code("the-code")
        respx.post(TOKEN_URI).respond(500, text="provider-body")
        with pytest.raises(service.WhoopProviderError):
            service.exchange_code("the-code")
        for secret in ("the-code", "access-1", "refresh-1", "whoop-client-secret", "provider-body"):
            assert secret not in caplog.text
