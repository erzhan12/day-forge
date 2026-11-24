"""``whoop_sync`` skeleton: model, crypto, admin and system checks (feature 0107)."""

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError
from django.test import override_settings
from whoop_sync import crypto
from whoop_sync.checks import (
    error_whoop_oauth_partial_config,
    warn_ineffective_cache_with_whoop_sync,
)
from whoop_sync.models import WhoopAccount

FERNET_KEY = Fernet.generate_key().decode()
OTHER_KEY = Fernet.generate_key().decode()
LOCMEM = "django.core.cache.backends.locmem.LocMemCache"
REDIS = "django.core.cache.backends.redis.RedisCache"

_NONE = dict(
    WHOOP_OAUTH_CLIENT_ID="",
    WHOOP_OAUTH_CLIENT_SECRET="",
    WHOOP_OAUTH_REDIRECT_URI="",
    WHOOP_OAUTH_TOKEN_KEY="",
)
_FULL = dict(
    WHOOP_OAUTH_CLIENT_ID="cid",
    WHOOP_OAUTH_CLIENT_SECRET="secret",
    WHOOP_OAUTH_REDIRECT_URI="https://app.test/api/whoop/callback/",
    WHOOP_OAUTH_TOKEN_KEY=FERNET_KEY,
)


@pytest.fixture
def account(db, settings):
    settings.WHOOP_OAUTH_TOKEN_KEY = FERNET_KEY
    user = User.objects.create_user(username="whoop-owner")
    acc = WhoopAccount(user=user, scopes="offline read:sleep")
    acc.set_refresh_token("refresh-plain-1")
    acc.set_access_token("access-plain-1")
    acc.save()
    return acc


class TestCrypto:
    def test_round_trip_with_the_whoop_key(self, settings):
        settings.WHOOP_OAUTH_TOKEN_KEY = FERNET_KEY
        ciphertext = crypto.encrypt_token("secret-value")
        assert b"secret-value" not in ciphertext
        assert crypto.decrypt_token(ciphertext) == "secret-value"

    def test_uses_its_own_key_not_googles(self, settings):
        settings.WHOOP_OAUTH_TOKEN_KEY = FERNET_KEY
        settings.GOOGLE_OAUTH_TOKEN_KEY = OTHER_KEY
        ciphertext = crypto.encrypt_token("x")
        assert Fernet(FERNET_KEY.encode()).decrypt(ciphertext) == b"x"

    def test_rotated_key_raises_a_safe_error(self, settings):
        settings.WHOOP_OAUTH_TOKEN_KEY = FERNET_KEY
        ciphertext = crypto.encrypt_token("secret-value")
        settings.WHOOP_OAUTH_TOKEN_KEY = OTHER_KEY
        with pytest.raises(ImproperlyConfigured) as excinfo:
            crypto.decrypt_token(ciphertext)
        assert "WHOOP_OAUTH_TOKEN_KEY" in str(excinfo.value)
        assert "secret-value" not in str(excinfo.value)

    def test_missing_key_raises(self, settings):
        settings.WHOOP_OAUTH_TOKEN_KEY = ""
        with pytest.raises(ImproperlyConfigured):
            crypto.encrypt_token("x")


class TestModel:
    def test_tokens_are_stored_encrypted(self, account):
        row = WhoopAccount.objects.get(pk=account.pk)
        assert b"refresh-plain-1" not in bytes(row.refresh_token_encrypted)
        assert b"access-plain-1" not in bytes(row.access_token_encrypted)
        assert row.get_refresh_token() == "refresh-plain-1"
        assert row.get_access_token() == "access-plain-1"

    def test_access_token_absent_returns_none(self, account):
        account.access_token_encrypted = None
        assert account.get_access_token() is None

    def test_str_never_shows_tokens(self, account):
        text = str(account) + repr(account)
        assert "plain" not in text
        assert "encrypted" not in text

    def test_one_account_per_user(self, account):
        duplicate = WhoopAccount(user=account.user)
        duplicate.set_refresh_token("other")
        with pytest.raises(IntegrityError):
            duplicate.save()


class TestAdmin:
    def test_change_page_never_renders_ciphertext(self, account, admin_client):
        response = admin_client.get(f"/admin/whoop_sync/whoopaccount/{account.pk}/change/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "refresh_token_encrypted" not in body
        assert "access_token_encrypted" not in body
        assert bytes(account.refresh_token_encrypted).decode() not in body

    def test_changelist_renders(self, account, admin_client):
        response = admin_client.get("/admin/whoop_sync/whoopaccount/")
        assert response.status_code == 200

    def test_admin_can_delete_to_disconnect_but_not_add_or_change(self, account, admin_client):
        from django.contrib.admin.sites import site

        model_admin = site._registry[WhoopAccount]
        request = admin_client.get("/admin/").wsgi_request
        assert model_admin.has_add_permission(request) is False
        assert model_admin.has_change_permission(request, account) is False
        assert model_admin.has_delete_permission(request, account) is True


class TestE001AllOrNone:
    def test_none_set_passes_in_production(self):
        with override_settings(DEBUG=False, **_NONE):
            assert error_whoop_oauth_partial_config(app_configs=None) == []

    def test_all_set_passes(self):
        with override_settings(DEBUG=False, **_FULL):
            assert error_whoop_oauth_partial_config(app_configs=None) == []

    @pytest.mark.parametrize("debug", [True, False])
    @pytest.mark.parametrize("missing", sorted(_FULL))
    def test_partial_config_errors_in_every_mode(self, debug, missing):
        with override_settings(DEBUG=debug, **{**_FULL, missing: ""}):
            errors = error_whoop_oauth_partial_config(app_configs=None)
        assert [e.id for e in errors] == ["whoop_sync.E001"]
        assert missing in errors[0].msg

    def test_single_var_set_lists_the_other_three(self):
        with override_settings(**{**_NONE, "WHOOP_OAUTH_CLIENT_ID": "cid"}):
            errors = error_whoop_oauth_partial_config(app_configs=None)
        assert len(errors) == 3
        assert {e.id for e in errors} == {"whoop_sync.E001"}

    def test_invalid_fernet_key_errors_without_echoing_it(self):
        with override_settings(**{**_FULL, "WHOOP_OAUTH_TOKEN_KEY": "not-a-key"}):
            errors = error_whoop_oauth_partial_config(app_configs=None)
        assert [e.id for e in errors] == ["whoop_sync.E001"]
        assert "not-a-key" not in errors[0].msg
        assert "not-a-key" not in (errors[0].hint or "")


class TestW001SharedCache:
    def test_warns_with_locmem_and_an_account(self, account):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": LOCMEM}}):
            warnings = warn_ineffective_cache_with_whoop_sync(app_configs=None)
        assert [w.id for w in warnings] == ["whoop_sync.W001"]

    def test_silent_with_redis(self, account):
        with override_settings(
            DEBUG=False,
            CACHES={"default": {"BACKEND": REDIS, "LOCATION": "redis://localhost:6379/0"}},
        ):
            assert warn_ineffective_cache_with_whoop_sync(app_configs=None) == []

    def test_silent_without_accounts(self, db):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": LOCMEM}}):
            assert warn_ineffective_cache_with_whoop_sync(app_configs=None) == []
