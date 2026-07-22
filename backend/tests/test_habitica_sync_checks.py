from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.core.checks import run_checks
from django.db.utils import OperationalError, ProgrammingError
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


def test_e001_blocks_on_missing_key_only(settings):
    """One secret missing must yield exactly its own error.

    The both-missing case asserts ``len == 2``, which passes even if the two
    branches were coupled (e.g. one condition emitting both messages). These
    single-secret cases pin that each branch fires independently and names
    the right variable.
    """
    settings.DEBUG = False
    settings.HABITICA_ENCRYPTION_KEY = ""
    settings.HABITICA_CLIENT_ID = "maintainer-user"
    errors = _habitica_e001()
    assert len(errors) == 1
    assert "HABITICA_ENCRYPTION_KEY" in errors[0].msg
    assert "HABITICA_CLIENT_ID" not in errors[0].msg
    # Pin the UNSET wording specifically. The malformed-key branch also names
    # HABITICA_ENCRYPTION_KEY, so without this the test would still pass if the
    # unset branch (and its early return) were deleted and an empty key simply
    # fell through to Fernet("") — reporting "not a valid Fernet key" instead.
    assert "is not set" in errors[0].msg
    assert "not a valid Fernet key" not in errors[0].msg


def test_e001_blocks_on_missing_client_id_only(settings):
    settings.DEBUG = False
    settings.HABITICA_ENCRYPTION_KEY = VALID_KEY
    settings.HABITICA_CLIENT_ID = ""
    errors = _habitica_e001()
    assert len(errors) == 1
    assert "HABITICA_CLIENT_ID" in errors[0].msg
    assert "HABITICA_ENCRYPTION_KEY" not in errors[0].msg
    assert "is not set" in errors[0].msg


def test_e001_silent_when_fully_configured(settings):
    """The complement of every blocking case — no false positive in a
    correctly configured production environment."""
    settings.DEBUG = False
    settings.HABITICA_ENCRYPTION_KEY = VALID_KEY
    settings.HABITICA_CLIENT_ID = "maintainer-user"
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


def test_w001_ignores_programming_error(settings):
    """The check catches ProgrammingError too — Postgres raises that (not
    OperationalError) for a missing relation, so on the intended production
    database only this branch protects the pre-migrate path."""
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
            side_effect=ProgrammingError("relation does not exist"),
        ):
            assert _habitica_w001() == []
