"""Upstream HTTP / validation error mapping."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_server import config
from mcp_server.app import STATUS_ERRORS
from mcp_server.tests.conftest import call_tool, tool_text


def test_bad_date_rejected_without_upstream(client):
    with respx.mock:
        route = respx.get(url__regex=r".*/api/export/daily/.*").respond(200, text="nope")
        result = call_tool(
            client,
            "get_daily_report",
            {"date": "abc"},
            headers={"Authorization": "Bearer x"},
        )
    assert result.get("isError") is True
    assert "YYYY-MM-DD" in tool_text(result)
    assert route.called is False


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (401, STATUS_ERRORS[401]),
        (403, STATUS_ERRORS[403]),
        (404, STATUS_ERRORS[404]),
        (429, STATUS_ERRORS[429]),
        (500, "day-forge error 500"),
    ],
)
@respx.mock
def test_status_mapped_to_tool_error(client, status, needle):
    respx.get(f"{config.api_base()}/api/export/daily/today/").respond(
        status, text='{"errors":{"detail":"INTERNAL_LEAK_DO_NOT_SHOW"}}'
    )
    result = call_tool(
        client,
        "get_daily_report",
        {"date": "today"},
        headers={"Authorization": "Bearer x"},
    )
    text = tool_text(result)
    assert result.get("isError") is True
    assert needle in text
    assert "INTERNAL_LEAK" not in text
    assert "web:8006" not in text


@respx.mock
def test_timeout_maps_to_unreachable(client):
    respx.get(f"{config.api_base()}/api/export/daily/today/").mock(
        side_effect=httpx.ConnectTimeout("slow")
    )
    result = call_tool(
        client,
        "get_daily_report",
        {"date": "today"},
        headers={"Authorization": "Bearer x"},
    )
    assert result.get("isError") is True
    assert "unreachable" in tool_text(result)
