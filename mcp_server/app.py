"""Stateless MCP proxy in front of the Day Forge daily export API."""

from __future__ import annotations

import re
from typing import Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp_server import config

# fullmatch with [0-9]: `$` would accept a trailing newline and `\d` non-ASCII digits.
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

# Backend response bodies never reach the client, only these fixed messages.
STATUS_ERRORS = {
    401: "invalid or missing day-forge export token",
    403: "invalid or missing day-forge export token",
    404: "no report for this date",
    429: "rate limited, try later",
}

server = MCPServer("day-forge")


@server.custom_route("/mcp/health", methods=["GET"])
async def health(_request: Request) -> Response:
    """Public liveness probe for compose/Caddy. Body stays minimal on purpose."""
    return JSONResponse({"status": "ok"})


@server.tool()
def ping() -> str:
    """Health check: returns 'pong'."""
    return "pong"


@server.tool()
async def get_daily_report(
    ctx: Context, date: str = "today", format: Literal["markdown", "json"] = "markdown"
) -> str:
    """Get the user's Day Forge daily schedule report.

    date: "today" or a YYYY-MM-DD date. format: "markdown" or "json".
    Requires an ``Authorization: Bearer <export token>`` request header;
    the token is forwarded unchanged to Day Forge and never stored.
    """
    if date != "today" and not DATE_RE.fullmatch(date):
        raise ToolError("date must be 'today' or YYYY-MM-DD")
    request_context = ctx.request_context
    request = request_context.request if request_context is not None else None
    authorization = request.headers.get("authorization") if request is not None else None
    if not authorization:
        raise ToolError("missing Authorization header")
    params = {"format": "json"} if format == "json" else None
    headers = {
        "Authorization": authorization,
        "Host": config.api_host(),
        "X-Forwarded-Proto": "https",
    }
    try:
        async with httpx.AsyncClient(timeout=config.request_timeout()) as client:
            resp = await client.get(
                f"{config.api_base()}/api/export/daily/{date}/",
                params=params,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise ToolError("day-forge is unreachable") from exc
    if not resp.is_success:
        raise ToolError(STATUS_ERRORS.get(resp.status_code, f"day-forge error {resp.status_code}"))
    return resp.text


def build_app():
    """Build the Streamable HTTP ASGI app. Call once per process (session manager)."""
    config.request_timeout()  # fail loud at startup on a bad MCP_REQUEST_TIMEOUT
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=config.allowed_hosts(),
            allowed_origins=config.allowed_origins(),
        ),
    )
