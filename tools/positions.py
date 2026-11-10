"""Appending to an agent's position history under a lock, so two writers cannot interleave."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from tools.paths import agent_dir, position_file

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


@contextmanager
def position_lock(signature: str) -> Iterator[None]:
    """An exclusive, process-wide lock on one agent's position history (a lock file next to it).

    A whole read-check-write must sit inside one `with`: reading, releasing, then writing (as the trade tool used to) lets two trades both see the same
    cash. POSIX only (Linux, macOS): without `fcntl` there is no lock, and this refuses to pretend there is.
    """
    if fcntl is None:  # pragma: no cover - Windows
        raise RuntimeError("position locking needs a POSIX system (Linux or macOS)")
    directory = agent_dir(signature)
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / ".position.lock", "a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_position_record(signature: str, record: dict[str, Any]) -> None:
    """Add one record (a JSON line) to the position history. Call it inside `position_lock`."""
    path = position_file(signature)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
