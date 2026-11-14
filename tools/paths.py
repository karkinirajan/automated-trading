"""Where the project keeps its files, and the one rule for what may be used as a path component."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
AGENT_DATA_DIR = DATA_DIR / "agent_data"

# An agent's "signature" (its model name, such as "claude-3.7-sonnet" or "gpt-5") names a folder under agent_data. It comes from a configuration file,
# so it is checked before it becomes part of a path: letters, digits, dot, dash and underscore, starting with a letter or digit.
_SIGNATURE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


def safe_signature(signature: object) -> str:
    """The signature, if it is safe to use as a folder name; ValueError otherwise (a path separator, `..`, a leading dot, an empty string, a non-string)."""
    if not isinstance(signature, str) or not _SIGNATURE.fullmatch(signature) or ".." in signature:
        raise ValueError(f"unsafe agent signature: {str(signature)[:40]!r}")
    return signature


def agent_dir(signature: str) -> Path:
    """The folder of one agent's data: positions, logs, runtime settings."""
    return AGENT_DATA_DIR / safe_signature(signature)


def position_file(signature: str) -> Path:
    """The JSON-lines file with one agent's position history."""
    return agent_dir(signature) / "position" / "position.jsonl"


def merged_prices_file() -> Path:
    """The merged price data every tool reads."""
    return DATA_DIR / "merged.jsonl"
