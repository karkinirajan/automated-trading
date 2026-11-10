"""Which agent is calling a tool.

The four tool servers are separate processes, started once and shared by every model in a run, so they cannot learn who is calling from their own
environment (that is how every order used to be booked to whichever agent the servers were started for). Each agent therefore sends its signature in an HTTP
header on every request (`AGENT_HEADER`, set in the agent's MCP connection settings) and a tool wraps its work in `calling_agent()`, which points the settings
store (`TODAY_DATE`, `IF_TRADE`, ...) at that agent's own runtime file for the length of the call. With no header nothing changes: the servers fall back to the
`SIGNATURE` / `RUNTIME_ENV_PATH` of their own environment.

The header is an identity, not a credential: the servers listen on the loopback address only (see `tools/server.py`) and the signature is checked to be a plain
folder name before it is used in a path.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from tools.paths import agent_dir, safe_signature

AGENT_HEADER = "x-agent-signature"
RUNTIME_ENV_NAME = ".runtime_env.json"

_signature: ContextVar[str | None] = ContextVar("calling_agent_signature", default=None)


def runtime_env_path_override() -> str | None:
    """The runtime settings file of the agent whose call is being served; None when no call from a named agent is in progress."""
    signature = _signature.get()
    return str(agent_dir(signature) / RUNTIME_ENV_NAME) if signature else None


def _header_signature() -> str | None:
    from fastmcp.server.dependencies import get_http_headers  # imported here: only the tool servers need FastMCP

    raw = get_http_headers().get(AGENT_HEADER)  # {} outside an HTTP request
    return safe_signature(raw) if raw else None


@contextmanager
def calling_agent() -> Iterator[str | None]:
    """Serve the current tool call as the agent named in the request header, and yield its signature (None when the request names none).

    Raises ValueError for a signature that is not a plain folder name, so a request cannot point the settings store at an arbitrary path."""
    token = _signature.set(_header_signature())
    try:
        yield _signature.get()
    finally:
        _signature.reset(token)
