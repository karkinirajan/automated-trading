"""Starting an MCP tool server the same way for all four of them."""

from __future__ import annotations

import os
from typing import Any

DEFAULT_HOST = "127.0.0.1"


def run_server(mcp: Any, port_variable: str, default_port: int) -> None:
    """Serve `mcp` over streamable HTTP on `MCP_HOST` (default 127.0.0.1) and the port in `port_variable`.

    The tool servers can place trades and read prices, and have no authentication, so they listen on the loopback address unless MCP_HOST says otherwise.
    """
    host = os.getenv("MCP_HOST", DEFAULT_HOST)
    port = int(os.getenv(port_variable, str(default_port)))
    mcp.run(transport="streamable-http", host=host, port=port)
