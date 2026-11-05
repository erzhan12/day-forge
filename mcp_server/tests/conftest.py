"""Shared fixtures for MCP protocol tests.

``build_app()`` creates a single-use session manager, so the ASGI app and
TestClient are module-scoped: one lifespan per test module.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from mcp_server.app import build_app

PROTOCOL_VERSION = "2025-06-18"
ACCEPT = "application/json, text/event-stream"


@pytest.fixture(scope="module")
def client():
    with TestClient(build_app()) as test_client:
        yield test_client


@pytest.fixture(scope="module", autouse=True)
def _initialize_mcp_session(client: TestClient):
    """Walk initialize → notifications/initialized once per module."""
    init = client.post(
        "/mcp",
        headers={"Content-Type": "application/json", "Accept": ACCEPT},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        },
    )
    assert init.status_code == 200, init.text
    notify = client.post(
        "/mcp",
        headers={"Content-Type": "application/json", "Accept": ACCEPT},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert notify.status_code in (200, 202), notify.text


def call_tool(
    client: TestClient,
    name: str,
    arguments: dict | None = None,
    *,
    headers: dict[str, str] | None = None,
    req_id: int = 2,
) -> dict:
    """POST tools/call and return the JSON-RPC ``result`` object."""
    req_headers = {
        "Content-Type": "application/json",
        "Accept": ACCEPT,
    }
    if headers:
        req_headers.update(headers)
    resp = client.post(
        "/mcp",
        headers=req_headers,
        json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "result" in body, body
    return body["result"]


def list_tools(client: TestClient) -> list[dict]:
    resp = client.post(
        "/mcp",
        headers={"Content-Type": "application/json", "Accept": ACCEPT},
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["result"]["tools"]


def tool_text(result: dict) -> str:
    """Concatenate text content blocks from a tools/call result."""
    parts = []
    for block in result.get("content", []):
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)
