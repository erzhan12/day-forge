"""HTTP tests for ``/api/user/export-token/`` (feature 0088).

Session-only management of the personal daily-export credential: status,
creation, duplicate creation, revocation, recreation, anonymous/Bearer-only
denial, owner isolation, cache headers, one-time disclosure, CSRF
enforcement, and stale release/account-identity headers.
"""

import json

import pytest
from django.contrib.auth.models import User
from schedules.export_tokens import authenticate, create_token
from schedules.models import PersonalExportToken

pytestmark = pytest.mark.django_db

URL = "/api/user/export-token/"


class TestStatus:
    def test_no_token_reports_has_token_false(self, auth_client):
        response = auth_client.get(URL)
        assert response.status_code == 200
        body = response.json()
        assert body == {"has_token": False, "created_at": None}

    def test_existing_token_reports_has_token_true_with_created_at_but_no_secret(
        self, auth_client, user
    ):
        raw_token, row = create_token(user.pk)
        response = auth_client.get(URL)
        body = response.json()
        assert body["has_token"] is True
        assert body["created_at"] == row.created_at.isoformat()
        assert "token" not in body
        assert "token_digest" not in body
        assert raw_token not in response.content.decode()


class TestCreation:
    def test_create_returns_201_with_raw_token_once(self, auth_client, user):
        response = auth_client.post(URL)
        assert response.status_code == 201
        body = response.json()
        assert body["has_token"] is True
        assert "created_at" in body
        assert authenticate(body["token"]) == user

    def test_create_persists_only_the_digest(self, auth_client, user):
        response = auth_client.post(URL)
        raw_token = response.json()["token"]
        row = PersonalExportToken.objects.get(user=user)
        assert row.token_digest != raw_token
        assert raw_token not in row.token_digest

    def test_duplicate_create_without_revoking_returns_409_token_exists(self, auth_client, user):
        first = auth_client.post(URL)
        second = auth_client.post(URL)
        assert second.status_code == 409
        assert second.json()["code"] == "token_exists"
        # Original token must still authenticate — the duplicate attempt
        # must not have replaced it.
        assert authenticate(first.json()["token"]) == user
        assert PersonalExportToken.objects.filter(user=user).count() == 1


class TestRevocationAndRecreation:
    def test_revoke_returns_204(self, auth_client, user):
        create_token(user.pk)
        response = auth_client.delete(URL)
        assert response.status_code == 204
        assert not PersonalExportToken.objects.filter(user=user).exists()

    def test_revoke_is_idempotent_when_absent(self, auth_client):
        response = auth_client.delete(URL)
        assert response.status_code == 204

    def test_recreate_after_revoke_succeeds_with_an_unrelated_credential(self, auth_client, user):
        first_raw, _ = create_token(user.pk)
        auth_client.delete(URL)
        response = auth_client.post(URL)
        assert response.status_code == 201
        second_raw = response.json()["token"]
        assert second_raw != first_raw
        assert authenticate(first_raw) is None
        assert authenticate(second_raw) == user


class TestDenial:
    def test_anonymous_get_returns_401_json_not_a_login_redirect(self, client):
        response = client.get(URL)
        assert response.status_code == 401
        assert response.json()["errors"]["detail"]
        assert response.get("Location") is None

    def test_anonymous_post_returns_401(self, client):
        response = client.post(URL)
        assert response.status_code == 401
        assert not PersonalExportToken.objects.exists()

    def test_anonymous_delete_returns_401(self, client):
        response = client.delete(URL)
        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["get", "post", "delete"])
    def test_bearer_credential_alone_is_rejected(self, client, method):
        owner = User.objects.create_user(username="bearer-only-owner")
        raw_token, _ = create_token(owner.pk)
        response = getattr(client, method)(URL, HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        assert response.status_code == 401

    @pytest.mark.parametrize("method", ["get", "post", "delete"])
    def test_bearer_credential_with_a_different_valid_session_is_still_rejected(
        self, auth_client, user, method
    ):
        """A Bearer header must be rejected outright on this endpoint even
        when a valid session is also present — it must never be silently
        ignored in favor of the session, since that would let a caller
        confirm whether an arbitrary token string is valid."""
        raw_token, _ = create_token(user.pk)
        response = getattr(auth_client, method)(URL, HTTP_AUTHORIZATION=f"Bearer {raw_token}")
        assert response.status_code == 401

    def test_inactive_session_owner_rejected(self, auth_client, user):
        user.is_active = False
        user.save(update_fields=["is_active"])
        response = auth_client.get(URL)
        assert response.status_code == 401


class TestOwnerIsolation:
    def test_each_user_manages_only_their_own_token(self, client):
        alice = User.objects.create_user(username="alice-token-owner", password="pw")
        bob = User.objects.create_user(username="bob-token-owner", password="pw")
        alice_raw, _ = create_token(alice.pk)

        client.force_login(bob)
        bob_status = client.get(URL).json()
        assert bob_status == {"has_token": False, "created_at": None}

        bob_create = client.post(URL)
        assert bob_create.status_code == 201
        bob_raw = bob_create.json()["token"]
        assert authenticate(alice_raw) == alice
        assert authenticate(bob_raw) == bob

        client.delete(URL)
        assert authenticate(alice_raw) == alice
        assert PersonalExportToken.objects.filter(user=alice).exists()
        assert not PersonalExportToken.objects.filter(user=bob).exists()


class TestCacheHeaders:
    @pytest.mark.parametrize("method", ["get", "post", "delete"])
    def test_every_response_is_private_no_store(self, auth_client, method):
        response = getattr(auth_client, method)(URL)
        assert response["Cache-Control"] == "private, no-store"

    def test_denial_response_is_also_private_no_store(self, client):
        response = client.get(URL)
        assert response["Cache-Control"] == "private, no-store"


class TestCsrfEnforcement:
    def test_post_without_csrf_token_rejected(self, csrf_client, user):
        csrf_client.force_login(user)
        response = csrf_client.post(URL)
        assert response.status_code == 403
        assert not PersonalExportToken.objects.filter(user=user).exists()

    def test_delete_without_csrf_token_rejected(self, csrf_client, user):
        create_token(user.pk)
        csrf_client.force_login(user)
        response = csrf_client.delete(URL)
        assert response.status_code == 403
        assert PersonalExportToken.objects.filter(user=user).exists()


class TestStaleReleaseAndAccountHeaders:
    def test_stale_frontend_version_rejects_create_before_the_view_executes(
        self, auth_client, user, settings
    ):
        from django.test import override_settings

        with override_settings(INERTIA_VERSION="release-b"):
            response = auth_client.post(URL, HTTP_X_FRONTEND_VERSION="release-a")
        assert response.status_code == 409
        assert response.json()["code"] == "frontend_outdated"
        assert not PersonalExportToken.objects.filter(user=user).exists()

    def test_session_mismatched_identity_header_rejects_the_write(self, client, user):
        other = User.objects.create_user(username="export-token-other-identity")
        client.force_login(other)
        response = client.post(URL, HTTP_X_SCHEDULE_USER=str(user.pk))
        assert response.status_code == 401
        assert response.json()["code"] == "session_invalid"
        assert not PersonalExportToken.objects.filter(user=other).exists()

    def test_current_session_identity_header_allows_the_write(self, client, user):
        client.force_login(user)
        response = client.post(URL, HTTP_X_SCHEDULE_USER=str(user.pk))
        assert response.status_code == 201


class TestUnsupportedMethods:
    @pytest.mark.parametrize("method", ["patch", "put"])
    def test_rejected_with_405(self, auth_client, method):
        response = getattr(auth_client, method)(
            URL, json.dumps({}), content_type="application/json"
        )
        assert response.status_code == 405
