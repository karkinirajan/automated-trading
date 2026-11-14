"""Starting an MCP tool server the same way for all four of them."""

from __future__ import annotations

import os
from typing import Any

DEFAULT_HOST = "127.0.0.1"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def run_server(mcp: Any, port_variable: str, default_port: int) -> None:
    """Serve `mcp` over streamable HTTP on `MCP_HOST` (default 127.0.0.1) and the port in `port_variable`.

    The tool servers can place trades and read prices for any agent that has a folder, so they listen on the loopback address unless MCP_HOST says otherwise,
    and then only if MCP_AUTH_TOKEN is set (the agents send it; see `tools/agent_context.py`). Raises RuntimeError otherwise.
    """
    host = os.getenv("MCP_HOST", DEFAULT_HOST)
    if host not in LOOPBACK_HOSTS and not os.getenv("MCP_AUTH_TOKEN"):
        raise RuntimeError(f"refusing to listen on {host!r}: set MCP_AUTH_TOKEN (a long random secret, the same for the agents and the servers) or use a loopback address")
    port = int(os.getenv(port_variable, str(default_port)))
    mcp.run(transport="streamable-http", host=host, port=port)
