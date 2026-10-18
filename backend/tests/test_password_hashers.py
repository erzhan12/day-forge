"""Keep the fast fixture hasher isolated from application settings."""

import json
import os
import subprocess
import sys

from django.conf import global_settings, settings
from django.contrib.auth.hashers import identify_hasher


def test_fixture_user_uses_fast_hasher(user):
    assert identify_hasher(user.password).algorithm == "md5"
    assert user.check_password("testpass123")
    assert not user.check_password("wrong")


def test_production_settings_keep_django_password_hashers(frontend_build):
    # A fresh interpreter does not load pytest's session overrides.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; "
            "from django.conf import settings; "
            "from django.contrib.auth.hashers import get_hasher; "
            "print(json.dumps([settings.DEBUG, settings.PASSWORD_HASHERS, "
            "get_hasher().algorithm]))",
        ],
        cwd=settings.BASE_DIR,
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "day_forge.settings",
            "DEBUG": "0",
            "FRONTEND_BUILD_DIR": str(frontend_build),
            "DJANGO_SECRET_KEY": "test-production-settings-only",
        },
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    debug, hashers, algorithm = json.loads(result.stdout)
    assert debug is False
    assert hashers == global_settings.PASSWORD_HASHERS
    assert algorithm == "pbkdf2_sha256"
