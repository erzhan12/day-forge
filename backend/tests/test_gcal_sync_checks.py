"""System-check tests for ``gcal_sync.checks``."""

from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.db.utils import OperationalError
from django.test import override_settings
from gcal_sync.checks import (
    error_google_oauth_config_missing_in_production,
    warn_ineffective_cache_with_gcal_sync,
)
from gcal_sync.models import GoogleCalendarAccount

LOCMEM = "django.core.cache.backends.locmem.LocMemCache"
FILEBASED = "django.core.cache.backends.filebased.FileBasedCache"
DUMMY = "django.core.cache.backends.dummy.DummyCache"
REDIS = "django.core.cache.backends.redis.RedisCache"

FERNET_KEY = Fernet.generate_key().decode()

# A fully-configured prod env (used as the baseline; individual tests blank
# one var to assert E001 fires).
_FULL = dict(
    DEBUG=False,
    GOOGLE_OAUTH_TOKEN_KEY=FERNET_KEY,
    GOOGLE_OAUTH_CLIENT_ID="cid",
    GOOGLE_OAUTH_CLIENT_SECRET="secret",
    GOOGLE_OAUTH_REDIRECT_URI="https://app.test/cb/",
)


@pytest.fixture
def _account(db, settings):
    settings.GOOGLE_OAUTH_TOKEN_KEY = FERNET_KEY
    user = User.objects.create_user(username="g", password="x")
    acc = GoogleCalendarAccount(user=user, google_account_id="s1", email="a@b.com")
    acc.set_refresh_token("r")
    acc.save()
    return acc


class TestW001IneffectiveCache:
    def test_fires_with_locmem_and_account(self, _account):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": LOCMEM}}):
            warnings = warn_ineffective_cache_with_gcal_sync(app_configs=None)
        assert len(warnings) == 1
        assert warnings[0].id == "gcal_sync.W001"

    def test_silent_with_no_account(self, db):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": LOCMEM}}):
            assert warn_ineffective_cache_with_gcal_sync(app_configs=None) == []

    @pytest.mark.parametrize("backend", [LOCMEM, FILEBASED, DUMMY])
    def test_fires_with_each_ineffective_backend(self, _account, backend):
        with override_settings(
            DEBUG=False,
            CACHES={"default": {"BACKEND": backend, "LOCATION": "/tmp/gcal-test"}},
        ):
            warnings = warn_ineffective_cache_with_gcal_sync(app_configs=None)
        assert len(warnings) == 1

    def test_silent_with_shared_cache(self, _account):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": REDIS}}):
            assert warn_ineffective_cache_with_gcal_sync(app_configs=None) == []

    def test_silent_when_debug(self, _account):
        with override_settings(DEBUG=True, CACHES={"default": {"BACKEND": LOCMEM}}):
            assert warn_ineffective_cache_with_gcal_sync(app_configs=None) == []

    def test_swallows_db_error_during_first_migrate(self):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": LOCMEM}}):
            with patch(
                "gcal_sync.models.GoogleCalendarAccount.objects.exists",
                side_effect=OperationalError("no such table"),
            ):
                assert warn_ineffective_cache_with_gcal_sync(app_configs=None) == []


class TestE001ConfigMissing:
    def test_silent_when_fully_configured(self):
        with override_settings(**_FULL):
            assert error_google_oauth_config_missing_in_production(app_configs=None) == []

    def test_silent_in_debug(self):
        with override_settings(
            DEBUG=True,
            GOOGLE_OAUTH_TOKEN_KEY="",
            GOOGLE_OAUTH_CLIENT_ID="",
            GOOGLE_OAUTH_CLIENT_SECRET="",
            GOOGLE_OAUTH_REDIRECT_URI="",
        ):
            assert error_google_oauth_config_missing_in_production(app_configs=None) == []

    def test_fires_when_token_key_missing(self):
        with override_settings(**{**_FULL, "GOOGLE_OAUTH_TOKEN_KEY": ""}):
            errors = error_google_oauth_config_missing_in_production(app_configs=None)
        assert any(e.id == "gcal_sync.E001" for e in errors)
        assert any("GOOGLE_OAUTH_TOKEN_KEY" in e.msg for e in errors)

    def test_fires_when_token_key_malformed(self):
        with override_settings(**{**_FULL, "GOOGLE_OAUTH_TOKEN_KEY": "not-valid"}):
            errors = error_google_oauth_config_missing_in_production(app_configs=None)
        assert any("not a valid Fernet key" in e.msg for e in errors)

    @pytest.mark.parametrize(
        "var", ["GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI"]
    )
    def test_fires_when_any_client_var_missing(self, var):
        with override_settings(**{**_FULL, var: ""}):
            errors = error_google_oauth_config_missing_in_production(app_configs=None)
        assert any(e.id == "gcal_sync.E001" for e in errors)
        assert any(var in e.msg for e in errors)

    def test_fires_even_with_no_accounts(self):
        """The hard-requirement divergence from CalDAV: E001 fires in prod
        even when no user has connected Google (no DB query at all)."""
        with override_settings(**{**_FULL, "GOOGLE_OAUTH_CLIENT_ID": ""}):
            errors = error_google_oauth_config_missing_in_production(app_configs=None)
        assert len(errors) >= 1
