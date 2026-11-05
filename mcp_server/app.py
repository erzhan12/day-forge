import os
import re
from typing import Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DAYFORGE_API_URL = os.environ.get("DAYFORGE_API_URL", "https://dayforge.habitreward.org").rstrip(
    "/"
)

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
    """
    if date != "today" and not DATE_RE.fullmatch(date):
        raise ToolError("date must be 'today' or YYYY-MM-DD")
    request = ctx.request_context.request
    authorization = request.headers.get("authorization") if request is not None else None
    if not authorization:
        raise ToolError("missing Authorization header")
    params = {"format": "json"} if format == "json" else None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{DAYFORGE_API_URL}/api/export/daily/{date}/",
                params=params,
                headers={"Authorization": authorization},
            )
    except httpx.HTTPError as exc:
        raise ToolError("day-forge is unreachable") from exc
    if not resp.is_success:
        raise ToolError(STATUS_ERRORS.get(resp.status_code, f"day-forge error {resp.status_code}"))
    return resp.text


def build_app():
    return server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True
    )
