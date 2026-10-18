"""Read the immutable frontend identity packaged with the application image."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True)
class FrontendRelease:
    version: str
    script: str
    styles: tuple[str, ...]


def load_frontend_release(directory: Path) -> FrontendRelease:
    try:
        data = json.loads((directory / ".vite" / "release.json").read_text())
        version, script, styles = data["version"], data["script"], data["styles"]
        if (
            not isinstance(version, str)
            or version == "development"
            or not re.fullmatch(r"[\w.:-]{1,160}", version)
        ):
            raise ValueError("Invalid release identity")
        if not isinstance(styles, list) or not isinstance(script, str):
            raise ValueError("Invalid release assets")
        for asset in [script, *styles]:
            if not isinstance(asset, str) or not re.fullmatch(r"assets/[\w.-]+", asset):
                raise ValueError("Invalid release asset path")
            if not (directory / asset).is_file():
                raise ValueError(f"Missing release asset: {asset}")
        return FrontendRelease(version, script, tuple(styles))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ImproperlyConfigured(
            "Frontend build is missing or invalid. "
            "Run make frontend-build before production startup."
        ) from error
