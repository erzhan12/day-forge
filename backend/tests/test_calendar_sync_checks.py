"""System-check tests for ``calendar_sync.checks``.

Covers tests #16-#20 from the plan: W001 with each ineffective backend,
W001 silent when no account / shared backend, W001 DB-error swallow on
first migrate, and E001 encryption-key-missing-in-prod.
"""

from unittest.mock import patch

import pytest
from calendar_sync.checks import (
    error_caldav_encryption_key_missing_in_production,
    warn_ineffective_cache_with_calendar_sync,
)
from calendar_sync.models import CalDAVAccount
from cryptography.fernet import Fernet
from django.contrib.auth.models import User
from django.db.utils import OperationalError
from django.test import override_settings

LOCMEM = "django.core.cache.backends.locmem.LocMemCache"
FILEBASED = "django.core.cache.backends.filebased.FileBasedCache"
DUMMY = "django.core.cache.backends.dummy.DummyCache"
REDIS = "django.core.cache.backends.redis.RedisCache"
MEMCACHED = "django.core.cache.backends.memcached.PyMemcacheCache"

FERNET_KEY = Fernet.generate_key().decode()


@pytest.fixture
def _key_set(settings):
    settings.CALDAV_ENCRYPTION_KEY = FERNET_KEY


@pytest.fixture
def _account(db, _key_set):
    user = User.objects.create_user(username="cal", password="x")
    acc = CalDAVAccount(user=user, apple_id="a@b.com",
                       base_url="https://caldav.icloud.com/")
    acc.set_password("p")
    acc.save()
    return acc


class TestW001IneffectiveCache:
    def test_w001_fires_with_locmem_and_account(self, _account):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": LOCMEM}}):
            warnings = warn_ineffective_cache_with_calendar_sync(app_configs=None)
        assert len(warnings) == 1
        assert warnings[0].id == "calendar_sync.W001"

    def test_w001_silent_with_no_account(self, db):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": LOCMEM}}):
            assert warn_ineffective_cache_with_calendar_sync(app_configs=None) == []

    @pytest.mark.parametrize("backend", [LOCMEM, FILEBASED, DUMMY])
    def test_w001_fires_with_each_ineffective_backend(self, _account, backend):
        with override_settings(
            DEBUG=False,
            CACHES={
                "default": {
                    "BACKEND": backend,
                    # FileBasedCache requires LOCATION; the check doesn't
                    # exercise the backend, but Django still validates settings.
                    "LOCATION": "/tmp/caldav-test-cache",
                }
            },
        ):
            warnings = warn_ineffective_cache_with_calendar_sync(app_configs=None)
        assert len(warnings) == 1
        assert warnings[0].id == "calendar_sync.W001"

    @pytest.mark.parametrize("backend", [REDIS, MEMCACHED])
    def test_w001_silent_with_shared_cache(self, _account, backend):
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": backend}}):
            assert warn_ineffective_cache_with_calendar_sync(app_configs=None) == []

    def test_w001_silent_when_debug_true(self, _account):
        with override_settings(DEBUG=True, CACHES={"default": {"BACKEND": LOCMEM}}):
            assert warn_ineffective_cache_with_calendar_sync(app_configs=None) == []

    def test_w001_swallows_db_error_during_first_migrate(self):
        """Pre-migrate state — CalDAVAccount table doesn't exist. The
        check MUST return [] rather than propagating OperationalError,
        otherwise ``manage.py migrate`` cannot run on a fresh database.
        """
        with override_settings(DEBUG=False, CACHES={"default": {"BACKEND": LOCMEM}}):
            with patch(
                "calendar_sync.models.CalDAVAccount.objects.exists",
                side_effect=OperationalError("no such table"),
            ):
                result = warn_ineffective_cache_with_calendar_sync(app_configs=None)
        assert result == []


class TestE001EncryptionKeyMissing:
    def test_e001_fires_when_key_missing_in_prod(self):
        with override_settings(DEBUG=False, CALDAV_ENCRYPTION_KEY=""):
            errors = error_caldav_encryption_key_missing_in_production(app_configs=None)
        assert len(errors) == 1
        assert errors[0].id == "calendar_sync.E001"
        assert "CALDAV_ENCRYPTION_KEY" in errors[0].msg

    def test_e001_silent_when_debug_true(self):
        with override_settings(DEBUG=True, CALDAV_ENCRYPTION_KEY=""):
            assert error_caldav_encryption_key_missing_in_production(app_configs=None) == []

    def test_e001_silent_when_key_set_in_prod(self):
        with override_settings(DEBUG=False, CALDAV_ENCRYPTION_KEY=FERNET_KEY):
            assert error_caldav_encryption_key_missing_in_production(app_configs=None) == []

    def test_e001_fires_when_key_is_malformed_in_prod(self):
        """A non-empty but invalid Fernet key would let prod boot, then
        crash on the first POST with ImproperlyConfigured. The check
        must catch the malformed key at startup (review iter-1 P1)."""
        with override_settings(DEBUG=False, CALDAV_ENCRYPTION_KEY="not-a-valid-fernet-key"):
            errors = error_caldav_encryption_key_missing_in_production(app_configs=None)
        assert len(errors) == 1
        assert errors[0].id == "calendar_sync.E001"
        assert "not a valid Fernet key" in errors[0].msg

    def test_e001_silent_when_malformed_key_in_debug(self):
        """Dev mode tolerates a malformed key — only the prod gate fires."""
        with override_settings(DEBUG=True, CALDAV_ENCRYPTION_KEY="not-a-valid-fernet-key"):
            assert error_caldav_encryption_key_missing_in_production(app_configs=None) == []
