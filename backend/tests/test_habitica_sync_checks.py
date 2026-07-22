from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.core.checks import run_checks
from django.db.utils import OperationalError
from django.test import override_settings
from habitica_sync import checks as habitica_checks
from habitica_sync.models import HabiticaAccount

VALID_KEY = Fernet.generate_key().decode()


def _messages(ids):
    return [m for m in run_checks() if m.id in ids]


def _habitica_e001():
    return habitica_checks.error_habitica_secrets_missing_in_production(None)


def _habitica_w001():
    return habitica_checks.warn_ineffective_cache_with_habitica_sync(None)


def test_e001_blocks_debug_false_when_key_or_client_id_missing(settings):
    settings.DEBUG = False
    settings.HABITICA_ENCRYPTION_KEY = ""
    settings.HABITICA_CLIENT_ID = ""
    errors = _habitica_e001()
    assert len(errors) == 2


def test_e001_allows_debug_true_without_secrets(settings):
    settings.DEBUG = True
    settings.HABITICA_ENCRYPTION_KEY = ""
    settings.HABITICA_CLIENT_ID = ""
    assert _habitica_e001() == []


def test_e001_rejects_malformed_key(settings):
    settings.DEBUG = False
    settings.HABITICA_ENCRYPTION_KEY = "not-a-fernet-key"
    settings.HABITICA_CLIENT_ID = "maintainer-user"
    errors = _habitica_e001()
    assert len(errors) == 1
    assert "not a valid Fernet key" in errors[0].msg


@pytest.mark.django_db
def test_w001_warns_on_ineffective_cache_with_account(settings, django_user_model):
    settings.DEBUG = False
    settings.HABITICA_ENCRYPTION_KEY = VALID_KEY
    settings.HABITICA_CLIENT_ID = "maintainer-user"
    user = django_user_model.objects.create_user(username="habitica-check-user")
    acc = HabiticaAccount(user=user, api_user_id="uid")
    acc.set_token("token")
    acc.save()

    with override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    ):
        warnings = _habitica_w001()

    assert len(warnings) == 1


def test_w001_ignores_pre_migrate_table_absence(settings):
    settings.DEBUG = False
    settings.HABITICA_ENCRYPTION_KEY = VALID_KEY
    settings.HABITICA_CLIENT_ID = "maintainer-user"
    with override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            }
        }
    ):
        with patch(
            "habitica_sync.models.HabiticaAccount.objects.exists",
            side_effect=OperationalError("no table"),
        ):
            assert _habitica_w001() == []
