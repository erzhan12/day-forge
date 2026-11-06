import uvicorn

from mcp_server import config
from mcp_server.app import build_app

if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=config.mcp_port())
