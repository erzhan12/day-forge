"""Protocol smoke: health, ping, tools/list schema."""

from __future__ import annotations

from mcp_server.tests.conftest import call_tool, list_tools, tool_text


def test_health_endpoint(client):
    resp = client.get("/mcp/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ping_returns_pong(client):
    result = call_tool(client, "ping")
    assert result.get("isError") is not True
    assert tool_text(result) == "pong"


def test_tools_list_includes_get_daily_report_with_format_enum(client):
    tools = {t["name"]: t for t in list_tools(client)}
    assert "ping" in tools
    assert "get_daily_report" in tools
    schema = tools["get_daily_report"]["inputSchema"]
    props = schema.get("properties", {})
    assert "date" in props
    assert "format" in props
    assert props["format"].get("enum") == ["markdown", "json"]
    # Context must not leak into the advertised schema.
    assert "ctx" not in props
