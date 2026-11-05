import os
from typing import Literal

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DAYFORGE_API_URL = os.environ.get("DAYFORGE_API_URL", "https://dayforge.habitreward.org").rstrip(
    "/"
)

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
    request = ctx.request_context.request
    authorization = request.headers.get("authorization") if request is not None else None
    if not authorization:
        raise ToolError("missing Authorization header")
    params = {"format": "json"} if format == "json" else None
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DAYFORGE_API_URL}/api/export/daily/{date}/",
            params=params,
            headers={"Authorization": authorization},
        )
    return resp.text


def build_app():
    return server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True
    )
