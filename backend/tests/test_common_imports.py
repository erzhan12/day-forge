"""Import smoke tests for shared integration modules used at Django startup."""

from common.integration_checks import ineffective_cache_with_accounts
from common.integration_crypto import fernet_for_setting


def test_integration_helpers_import_successfully():
    assert callable(ineffective_cache_with_accounts)
    assert callable(fernet_for_setting)
