"""WHOOP connect / callback views (feature 0107, step 6)."""

import logging
import urllib.parse
from unittest.mock import patch

import pytest
import respx
from whoop_sync import views
from whoop_sync.models import WhoopAccount

from tests.whoop_helpers import AUTH_URI, SCOPES, TOKEN_URI, WHOOP_SETTINGS, token_body

CONNECT = "/api/whoop/connect/"
CALLBACK = "/api/whoop/callback/"


@pytest.fixture(autouse=True)
def _whoop_settings(settings):
    for name, value in WHOOP_SETTINGS.items():
        setattr(settings, name, value)


def _set_state(client, state):
    session = client.session
    session["whoop_oauth_state"] = state
    session.save()


class TestConnect:
    def test_requires_login(self, client, db):
        response = client.get(CONNECT)
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    def test_redirects_to_consent_with_an_eight_character_session_state(self, auth_client):
        response = auth_client.get(CONNECT)
        assert response.status_code == 302
        location = response["Location"]
        assert location.startswith(AUTH_URI + "?")
        state = auth_client.session["whoop_oauth_state"]
        assert len(state) == 8
        assert urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)["state"] == [state]

    def test_each_connect_issues_a_new_state(self, auth_client):
        auth_client.get(CONNECT)
        first = auth_client.session["whoop_oauth_state"]
        states = {first}
        for _ in range(5):
            auth_client.get(CONNECT)
            states.add(auth_client.session["whoop_oauth_state"])
        assert len(states) > 1

    def test_post_not_allowed(self, auth_client):
        assert auth_client.post(CONNECT).status_code == 405

    def test_not_configured(self, auth_client, settings):
        for name in WHOOP_SETTINGS:
            setattr(settings, name, "")
        response = auth_client.get(CONNECT)
        assert response.status_code == 503
        assert response.content.decode() == "WHOOP is not configured"
        assert "whoop_oauth_state" not in auth_client.session


class TestCallback:
    def test_requires_login(self, client, db):
        response = client.get(CALLBACK + "?state=ab12cd34&code=x")
        assert response.status_code == 302
        assert "/accounts/login/" in response["Location"]

    @respx.mock
    def test_success_stores_encrypted_tokens_and_shows_plain_page(self, auth_client, user):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        _set_state(auth_client, "ab12cd34")
        response = auth_client.get(CALLBACK + "?state=ab12cd34&code=the-code&scope=x")
        assert response.status_code == 200
        assert response.content.decode() == "WHOOP connected"
        assert response["Content-Type"].startswith("text/plain")
        assert response["Cache-Control"] == "private, no-store"
        assert route.call_count == 1
        account = WhoopAccount.objects.get(user=user)
        assert account.get_refresh_token() == "refresh-1"
        assert account.get_access_token() == "access-1"
        assert account.scopes == SCOPES
        assert account.access_token_expiry is not None
        assert account.last_verified_at is not None

    @respx.mock
    def test_reconnect_updates_the_existing_row(self, auth_client, user):
        respx.post(TOKEN_URI).respond(200, json=token_body(access="a-1", refresh="r-1"))
        _set_state(auth_client, "ab12cd34")
        auth_client.get(CALLBACK + "?state=ab12cd34&code=c1")
        first = WhoopAccount.objects.get(user=user)

        respx.post(TOKEN_URI).respond(200, json=token_body(access="a-2", refresh="r-2"))
        _set_state(auth_client, "ef56ab78")
        response = auth_client.get(CALLBACK + "?state=ef56ab78&code=c2")
        assert response.content.decode() == "WHOOP connected"
        assert WhoopAccount.objects.filter(user=user).count() == 1
        account = WhoopAccount.objects.get(user=user)
        assert account.pk == first.pk
        assert account.get_refresh_token() == "r-2"

    @pytest.mark.parametrize(
        "session_state,query",
        [
            ("ab12cd34", "?state=zz12cd34&code=c"),
            ("ab12cd34", "?code=c"),
            (None, "?state=ab12cd34&code=c"),
            ("ab12cd34", "?state=ab12cd3&code=c"),
        ],
        ids=["mismatch", "missing-query-state", "missing-session-state", "prefix"],
    )
    @respx.mock
    def test_state_problems_fail_without_exchange(self, auth_client, user, session_state, query):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        if session_state is not None:
            _set_state(auth_client, session_state)
        response = auth_client.get(CALLBACK + query)
        assert response.status_code == 400
        assert response.content.decode() == "WHOOP connection failed"
        assert route.called is False
        assert not WhoopAccount.objects.exists()

    @respx.mock
    def test_state_is_single_use(self, auth_client, user):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        _set_state(auth_client, "ab12cd34")
        assert auth_client.get(CALLBACK + "?state=ab12cd34&code=c").status_code == 200
        replay = auth_client.get(CALLBACK + "?state=ab12cd34&code=c")
        assert replay.status_code == 400
        assert route.call_count == 1

    @respx.mock
    def test_state_is_popped_even_when_it_mismatches(self, auth_client, user):
        _set_state(auth_client, "ab12cd34")
        auth_client.get(CALLBACK + "?state=zz12cd34&code=c")
        assert "whoop_oauth_state" not in auth_client.session

    def test_state_is_compared_in_constant_time(self, auth_client, user):
        _set_state(auth_client, "ab12cd34")
        # Replace only the views module's ``secrets`` binding: the session
        # backend uses ``secrets.compare_digest`` too.
        with patch.object(views, "secrets") as fake_secrets:
            fake_secrets.compare_digest.return_value = False
            response = auth_client.get(CALLBACK + "?state=ab12cd34&code=c")
        fake_secrets.compare_digest.assert_called_once_with("ab12cd34", "ab12cd34")
        assert response.status_code == 400

    @respx.mock
    def test_denied(self, auth_client, user):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        _set_state(auth_client, "ab12cd34")
        response = auth_client.get(CALLBACK + "?state=ab12cd34&error=access_denied")
        assert response.status_code == 400
        assert response.content.decode() == "WHOOP connection failed"
        assert route.called is False
        assert not WhoopAccount.objects.exists()

    @respx.mock
    def test_missing_code(self, auth_client, user):
        route = respx.post(TOKEN_URI).respond(200, json=token_body())
        _set_state(auth_client, "ab12cd34")
        response = auth_client.get(CALLBACK + "?state=ab12cd34")
        assert response.status_code == 400
        assert route.called is False

    @pytest.mark.parametrize("status", [400, 429, 500])
    @respx.mock
    def test_provider_error_fails_without_storing_or_leaking(
        self, auth_client, user, caplog, status
    ):
        caplog.set_level(logging.DEBUG)
        respx.post(TOKEN_URI).respond(status, text="PROVIDER_BODY")
        _set_state(auth_client, "ab12cd34")
        response = auth_client.get(CALLBACK + "?state=ab12cd34&code=secret-code")
        assert response.status_code == 502
        assert response.content.decode() == "WHOOP connection failed"
        assert not WhoopAccount.objects.exists()
        assert "PROVIDER_BODY" not in caplog.text
        assert "secret-code" not in caplog.text

    def test_unexpected_exception_is_a_failure_page(self, auth_client, user):
        _set_state(auth_client, "ab12cd34")
        with patch.object(views.service, "exchange_code", side_effect=RuntimeError("x")):
            response = auth_client.get(CALLBACK + "?state=ab12cd34&code=c")
        assert response.status_code == 502
        assert response.content.decode() == "WHOOP connection failed"

    def test_not_configured(self, auth_client, settings):
        for name in WHOOP_SETTINGS:
            setattr(settings, name, "")
        _set_state(auth_client, "ab12cd34")
        response = auth_client.get(CALLBACK + "?state=ab12cd34&code=c")
        assert response.status_code == 503
        assert response.content.decode() == "WHOOP is not configured"
