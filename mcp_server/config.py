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
    raw = os.environ.get("MCP_REQUEST_TIMEOUT", "10")
    value = float(raw)
    if value <= 0:
        raise ValueError("MCP_REQUEST_TIMEOUT must be > 0")
    return value


def mcp_port() -> int:
    return int(os.environ.get("MCP_PORT", "8007"))


def _csv_env(name: str, default: str) -> list[str]:
    raw = os.environ.get(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def allowed_hosts() -> list[str]:
    """DNS-rebinding allowlist for the public MCP Host header.

    Local default covers Inspector and Starlette's TestClient host.
    Production compose sets ``dayforge.habitreward.org`` only.
    """
    return _csv_env(
        "MCP_ALLOWED_HOSTS",
        "localhost,localhost:*,127.0.0.1,127.0.0.1:*,testserver",
    )


def allowed_origins() -> list[str]:
    """DNS-rebinding allowlist for browser ``Origin`` headers.

    Requests without ``Origin`` (Claude Code, curl) always pass. Empty list
    would 403 every browser client, so defaults cover claude.ai + the site.
    """
    return _csv_env(
        "MCP_ALLOWED_ORIGINS",
        "https://claude.ai,https://www.claude.ai,https://dayforge.habitreward.org,"
        "http://localhost,http://localhost:*,http://127.0.0.1,http://127.0.0.1:*",
    )
