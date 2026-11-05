import os
from typing import Literal

import httpx
from mcp.server.mcpserver import MCPServer

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
    date: str = "today", format: Literal["markdown", "json"] = "markdown"
) -> str:
    """Get the user's Day Forge daily schedule report.

    date: "today" or a YYYY-MM-DD date. format: "markdown" or "json".
    """
    # Local testing only: step 3 replaces this with the calling client's token.
    token = os.environ["DAYFORGE_TOKEN"]
    params = {"format": "json"} if format == "json" else None
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DAYFORGE_API_URL}/api/export/daily/{date}/",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        )
    return resp.text


def build_app():
    return server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True
    )
