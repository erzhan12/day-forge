"""WHOOP settings and deploy wiring (feature 0107, step 3).

WHOOP is optional at boot: every ``WHOOP_OAUTH_*`` value defaults to empty,
and the deploy workflow passes the four secrets through ``optional()`` so an
unset secret omits the line instead of failing the deploy.
"""

import re
from pathlib import Path

import pytest

from tests.test_settings_validation import _exec_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
WHOOP_OAUTH_VARS = (
    "WHOOP_OAUTH_CLIENT_ID",
    "WHOOP_OAUTH_CLIENT_SECRET",
    "WHOOP_OAUTH_REDIRECT_URI",
    "WHOOP_OAUTH_TOKEN_KEY",
)


@pytest.fixture(autouse=True)
def _production_build(monkeypatch, frontend_build):
    monkeypatch.setenv("FRONTEND_BUILD_DIR", str(frontend_build))


def test_whoop_oauth_values_default_to_empty(monkeypatch):
    for name in WHOOP_OAUTH_VARS:
        monkeypatch.delenv(name, raising=False)
    ns = _exec_settings(monkeypatch)
    for name in WHOOP_OAUTH_VARS:
        assert ns[name] == ""


def test_whoop_endpoints_and_scopes_are_constants(monkeypatch):
    ns = _exec_settings(monkeypatch)
    assert ns["WHOOP_OAUTH_AUTH_URI"] == "https://api.prod.whoop.com/oauth/oauth2/auth"
    assert ns["WHOOP_OAUTH_TOKEN_URI"] == "https://api.prod.whoop.com/oauth/oauth2/token"
    assert ns["WHOOP_API_BASE"] == "https://api.prod.whoop.com/developer"
    assert ns["WHOOP_OAUTH_SCOPE"].split() == [
        "offline", "read:recovery", "read:cycles", "read:sleep", "read:workout",
    ]
    assert ns["WHOOP_REQUEST_TIMEOUT"] == 10.0


@pytest.mark.parametrize("value", ["0", "-1"])
def test_non_positive_whoop_timeout_raises_at_import(monkeypatch, value):
    with pytest.raises(ValueError, match="WHOOP_REQUEST_TIMEOUT"):
        _exec_settings(monkeypatch, WHOOP_REQUEST_TIMEOUT=value)


def test_env_example_lists_every_whoop_var_with_an_empty_value():
    text = (REPO_ROOT / ".env.example").read_text()
    for name in WHOOP_OAUTH_VARS:
        assert re.search(rf"^{name}=$", text, re.MULTILINE), name


def test_deploy_passes_whoop_secrets_through_optional_never_require():
    text = (REPO_ROOT / ".github" / "workflows" / "deploy.yml").read_text()
    for name in WHOOP_OAUTH_VARS:
        assert f"{name}: ${{{{ secrets.{name} }}}}" in text, name
        assert f'optional("{name}")' in text, name
        assert f'require("{name}")' not in text, name
