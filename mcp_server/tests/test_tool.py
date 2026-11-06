"""Successful get_daily_report proxying."""

from __future__ import annotations

import respx

from mcp_server import config
from mcp_server.tests.conftest import call_tool, tool_text


@respx.mock
def test_success_markdown_default(client):
    route = respx.get(f"{config.api_base()}/api/export/daily/2026-08-29/").respond(
        200, text="## day-forge · 2026-08-29"
    )
    result = call_tool(
        client,
        "get_daily_report",
        {"date": "2026-08-29"},
        headers={"Authorization": "Bearer dfx_ok"},
    )
    assert result.get("isError") is not True
    assert tool_text(result) == "## day-forge · 2026-08-29"
    assert route.calls.last.request.url.params.get("format") is None


@respx.mock
def test_format_json_adds_query_param(client):
    route = respx.get(f"{config.api_base()}/api/export/daily/today/").respond(
        200, text='{"date":"2026-08-29","markdown":"..."}'
    )
    result = call_tool(
        client,
        "get_daily_report",
        {"date": "today", "format": "json"},
        headers={"Authorization": "Bearer dfx_ok"},
    )
    assert result.get("isError") is not True
    assert '"date"' in tool_text(result)
    assert route.calls.last.request.url.params["format"] == "json"
