"""Builders for the project's data files in a temporary directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def bar(open_: float | None, close: float | None = None, high: float | None = None, low: float | None = None, volume: int = 1000) -> dict[str, Any]:
    """One price bar in the merged file's layout."""
    out: dict[str, Any] = {}
    if open_ is not None:
        out["1. buy price"] = str(open_)
    if high is not None or close is not None:
        out["2. high"] = str(high if high is not None else (close or 0) + 1)
        out["3. low"] = str(low if low is not None else (close or 0) - 1)
    if close is not None:
        out["4. sell price"] = str(close)
        out["5. volume"] = str(volume)
    return out


def write_prices(data_dir: Path, symbols: dict[str, dict[str, dict[str, Any]]], *, hourly: bool = False) -> Path:
    """Write data/merged.jsonl: one document per symbol with its {date: bar} series."""
    path = data_dir / "merged.jsonl"
    key = "Time Series (60min)" if hourly else "Time Series (Daily)"
    with path.open("w", encoding="utf-8") as handle:
        for symbol, series in symbols.items():
            handle.write(json.dumps({"Meta Data": {"2. Symbol": symbol}, key: series}) + "\n")
    return path


def write_positions(agent_dir: Path, records: list[dict[str, Any]]) -> Path:
    """Write an agent's position.jsonl."""
    path = agent_dir / "position" / "position.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def read_positions(agent_dir: Path) -> list[dict[str, Any]]:
    path = agent_dir / "position" / "position.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
