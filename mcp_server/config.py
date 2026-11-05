"""Environment-backed settings for the MCP proxy.

Values are read at call time so tests can monkeypatch ``os.environ``.
"""

from __future__ import annotations

import os


def api_base() -> str:
    """Upstream Day Forge base URL (no trailing slash).

    Default ``http://web:8006`` hits the compose-internal Django service.
    Local Inspector against production can override with the public HTTPS URL;
    ``DAYFORGE_API_URL`` remains accepted as a legacy alias.
    """
    raw = os.environ.get("DAYFORGE_API_BASE") or os.environ.get(
        "DAYFORGE_API_URL", "http://web:8006"
    )
    return raw.rstrip("/")


def api_host() -> str:
    """Host header sent to Django (``ALLOWED_HOSTS`` / proxy-SSL)."""
    return os.environ.get("DAYFORGE_API_HOST", "dayforge.habitreward.org")


def request_timeout() -> float:
    return float(os.environ.get("MCP_REQUEST_TIMEOUT", "10"))


def mcp_port() -> int:
    return int(os.environ.get("MCP_PORT", "8007"))


def allowed_hosts() -> list[str]:
    """DNS-rebinding allowlist for the public MCP Host header.

    Local default covers Inspector and Starlette's TestClient host.
    Production compose sets ``dayforge.habitreward.org`` only.
    """
    raw = os.environ.get(
        "MCP_ALLOWED_HOSTS",
        "localhost,localhost:*,127.0.0.1,127.0.0.1:*,testserver",
    )
    return [part.strip() for part in raw.split(",") if part.strip()]
