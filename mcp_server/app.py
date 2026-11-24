"""Stateless MCP proxy in front of the Day Forge export API (daily report, WHOOP day)."""

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

# get_whoop_day (feature 0107): 404 and 409 mean different things there.
WHOOP_STATUS_ERRORS = {
    **STATUS_ERRORS,
    404: "WHOOP is not connected",
    409: "WHOOP needs to be reconnected",
    502: "WHOOP is unavailable, try later",
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


def _validate_date(date: str) -> None:
    if date != "today" and not DATE_RE.fullmatch(date):
        raise ToolError("date must be 'today' or YYYY-MM-DD")


async def _forward(
    ctx: Context, path: str, params: dict[str, str] | None, errors: dict[int, str]
) -> str:
    """GET ``path`` on Day Forge with the caller's ``Authorization`` header.

    The header is forwarded unchanged and never stored or logged. A failure
    becomes a fixed message from ``errors``; upstream bodies never pass.
    """
    request_context = ctx.request_context
    request = request_context.request if request_context is not None else None
    authorization = request.headers.get("authorization") if request is not None else None
    if not authorization:
        raise ToolError("missing Authorization header")
    headers = {
        "Authorization": authorization,
        "Host": config.api_host(),
        "X-Forwarded-Proto": "https",
    }
    try:
        async with httpx.AsyncClient(timeout=config.request_timeout()) as client:
            resp = await client.get(f"{config.api_base()}{path}", params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise ToolError("day-forge is unreachable") from exc
    if not resp.is_success:
        raise ToolError(errors.get(resp.status_code, f"day-forge error {resp.status_code}"))
    return resp.text


@server.tool()
async def get_daily_report(
    ctx: Context, date: str = "today", format: Literal["markdown", "json"] = "markdown"
) -> str:
    """Get the user's Day Forge daily schedule report.

    date: "today" or a YYYY-MM-DD date. format: "markdown" or "json".
    Requires an ``Authorization: Bearer <export token>`` request header;
    the token is forwarded unchanged to Day Forge and never stored.
    """
    _validate_date(date)
    params = {"format": "json"} if format == "json" else None
    return await _forward(ctx, f"/api/export/daily/{date}/", params, STATUS_ERRORS)


@server.tool()
async def get_whoop_day(ctx: Context, date: str = "today") -> str:
    """Get the user's WHOOP morning summary for a day as Markdown.

    Recovery, last night's sleep, the previous day's strain and workouts.
    date: "today" or a YYYY-MM-DD date. Requires the same
    ``Authorization: Bearer <export token>`` header as get_daily_report;
    the token is forwarded unchanged and never stored.
    """
    _validate_date(date)
    return await _forward(ctx, f"/api/export/whoop/{date}/", None, WHOOP_STATUS_ERRORS)


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
