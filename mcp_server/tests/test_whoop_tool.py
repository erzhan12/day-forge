"""get_whoop_day: forwarding and error mapping (feature 0107)."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_server import config
from mcp_server.tests.conftest import call_tool, list_tools, tool_text

LEAK = '{"errors":{"detail":"INTERNAL_LEAK_DO_NOT_SHOW"}}'


def test_tools_list_includes_get_whoop_day(client):
    tools = {t["name"]: t for t in list_tools(client)}
    assert "get_whoop_day" in tools
    props = tools["get_whoop_day"]["inputSchema"].get("properties", {})
    assert set(props) == {"date"}
    assert props["date"].get("default") == "today"


@respx.mock
def test_forwards_authorization_verbatim_and_returns_markdown(client):
    route = respx.get(f"{config.api_base()}/api/export/whoop/2026-11-23/").respond(
        200, text="## whoop · 2026-11-23\n"
    )
    token = "Bearer dfx_whoop_value"
    result = call_tool(
        client, "get_whoop_day", {"date": "2026-11-23"}, headers={"Authorization": token}
    )
    assert result.get("isError") is not True
    assert tool_text(result) == "## whoop · 2026-11-23\n"
    request = route.calls.last.request
    assert request.headers["authorization"] == token
    assert request.headers["host"] == config.api_host()
    assert request.headers["x-forwarded-proto"] == "https"
    assert dict(request.url.params) == {}


@respx.mock
def test_default_date_is_today(client):
    route = respx.get(f"{config.api_base()}/api/export/whoop/today/").respond(200, text="ok")
    call_tool(client, "get_whoop_day", {}, headers={"Authorization": "Bearer x"})
    assert route.called is True


@respx.mock
def test_missing_authorization_fails_without_calling_day_forge(client):
    route = respx.get(url__regex=r".*/api/export/whoop/.*").respond(200, text="secret")
    result = call_tool(client, "get_whoop_day", {"date": "today"})
    assert result.get("isError") is True
    assert "Authorization" in tool_text(result)
    assert route.called is False


@pytest.mark.parametrize("date", ["abc", "2026-11-23\n", "2026-1-23", "２０２６-11-23"])
@respx.mock
def test_bad_date_rejected_without_upstream(client, date):
    route = respx.get(url__regex=r".*/api/export/whoop/.*").respond(200, text="nope")
    result = call_tool(
        client, "get_whoop_day", {"date": date}, headers={"Authorization": "Bearer x"}
    )
    assert result.get("isError") is True
    assert "YYYY-MM-DD" in tool_text(result)
    assert route.called is False


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "invalid or missing day-forge export token"),
        (403, "invalid or missing day-forge export token"),
        (404, "WHOOP is not connected"),
        (409, "WHOOP needs to be reconnected"),
        (429, "rate limited, try later"),
        (502, "WHOOP is unavailable, try later"),
        (500, "day-forge error 500"),
    ],
)
@respx.mock
def test_status_mapped_to_fixed_message(client, status, message):
    respx.get(f"{config.api_base()}/api/export/whoop/today/").respond(status, text=LEAK)
    result = call_tool(
        client, "get_whoop_day", {"date": "today"}, headers={"Authorization": "Bearer x"}
    )
    text = tool_text(result)
    assert result.get("isError") is True
    assert message in text
    assert "INTERNAL_LEAK" not in text


@respx.mock
def test_unreachable(client):
    respx.get(f"{config.api_base()}/api/export/whoop/today/").mock(
        side_effect=httpx.ConnectError("down")
    )
    result = call_tool(
        client, "get_whoop_day", {"date": "today"}, headers={"Authorization": "Bearer x"}
    )
    assert result.get("isError") is True
    assert "unreachable" in tool_text(result)
