from mcp.server.mcpserver import MCPServer

server = MCPServer("day-forge")


@server.tool()
def ping() -> str:
    """Health check: returns 'pong'."""
    return "pong"


def build_app():
    return server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True
    )
