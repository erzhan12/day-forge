"""Authorization header forwarding."""

from __future__ import annotations

import respx

from mcp_server import config
from mcp_server.tests.conftest import call_tool, tool_text


@respx.mock
def test_missing_authorization_is_tool_error_without_upstream(client):
    route = respx.get(url__regex=r".*/api/export/daily/.*").respond(200, text="secret")
    result = call_tool(client, "get_daily_report", {"date": "today"})
    assert result.get("isError") is True
    assert "Authorization" in tool_text(result)
    assert route.called is False


@respx.mock
def test_authorization_forwarded_verbatim_with_host_headers(client):
    route = respx.get(f"{config.api_base()}/api/export/daily/today/").respond(
        200, text="## report"
    )
    token = "Bearer dfx_test_token_value"
    result = call_tool(
        client,
        "get_daily_report",
        {"date": "today"},
        headers={"Authorization": token},
    )
    assert result.get("isError") is not True
    assert tool_text(result) == "## report"
    assert route.called is True
    sent = route.calls.last.request.headers
    assert sent["authorization"] == token
    assert sent["host"] == config.api_host()
    assert sent["x-forwarded-proto"] == "https"
