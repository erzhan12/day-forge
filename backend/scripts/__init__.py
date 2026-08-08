"""Auditable seed helpers used by the Playwright smoke harness.

Shared env-var accessors live here so every seeder diagnoses a missing
``SEED_*`` variable uniformly (a ``RuntimeError`` naming the variable) rather
than each module raising its own bare ``KeyError``.
"""

import json
import os
from typing import Any

from django.contrib.auth.models import User


def _required(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"{name} is required")
    return value


def _json(name: str, default: Any = None) -> Any:
    value = os.environ.get(name)
    return default if value is None else json.loads(value)


def _user() -> User:
    return User.objects.get(username=_required("SEED_USERNAME"))
