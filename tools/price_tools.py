"""Reading prices and positions from the project's data files.

Prices come from `data/merged.jsonl` (one JSON document per symbol, in Alpha Vantage's layout with the open renamed "1. buy price" and the close "4. sell price");
positions come from each agent's `position.jsonl`.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Allow running this file directly from a subdirectory
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tools.constants import NASDAQ_100_SYMBOLS
from tools.paths import merged_prices_file, position_file

# Re-export for backwards compatibility
all_nasdaq_100_symbols = NASDAQ_100_SYMBOLS


def _price_documents(merged_path: str | None, series_name: str | None = None) -> Iterator[tuple[str, dict[str, Any]]]:
    """(symbol, time series) for every symbol in the merged price file. Blank lines, damaged lines and documents without a series are skipped.

    `series_name` ("(Daily)" or "(60min)") keeps only documents whose "Time Series ..." key contains it; by default the first such key is used."""
    merged_file = Path(merged_path) if merged_path is not None else merged_prices_file()
    if not merged_file.exists():
        return
    with merged_file.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(doc, dict):
                continue
            meta = doc.get("Meta Data", {})
            symbol = meta.get("2. Symbol") if isinstance(meta, dict) else None
            series = next(
                (value for key, value in doc.items() if key.startswith("Time Series") and (series_name is None or series_name in key)),
                None,
            )
            if isinstance(symbol, str) and isinstance(series, dict):
                yield symbol, series


def get_price_timestamps(merged_path: str | None = None) -> set[str]:
    """Every date (or date and time) that has a bar for at least one symbol."""
    return {stamp for _, series in _price_documents(merged_path) for stamp in series}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _step_back(input_dt: datetime, date_only: bool) -> str:
    """The previous trading moment when the data cannot say: one weekday back for a date, one hour back for a time."""
    if date_only:
        previous = input_dt - timedelta(days=1)
        while previous.weekday() >= 5:
            previous -= timedelta(days=1)
        return previous.strftime("%Y-%m-%d")
    return (input_dt - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")


def get_yesterday_date(today_date: str, merged_path: str | None = None) -> str:
    """The trading date or time before `today_date`, found in the price data (the previous weekday or hour when the data has no earlier point).

    Args:
        today_date: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS".
        merged_path: another merged price file; the default is data/merged.jsonl.

    Returns:
        The previous point in the same format as the input.
    """
    date_only = " " not in today_date
    input_dt = datetime.strptime(today_date, "%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M:%S")

    previous: datetime | None = None
    for _symbol, series in _price_documents(merged_path):
        for stamp in series:
            try:
                moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError):
                try:
                    moment = datetime.strptime(stamp, "%Y-%m-%d")
                except (TypeError, ValueError):
                    continue
            if moment < input_dt and (previous is None or moment > previous):
                previous = moment

    if previous is None:
        return _step_back(input_dt, date_only)
    return previous.strftime("%Y-%m-%d" if date_only else "%Y-%m-%d %H:%M:%S")


def get_open_prices(today_date: str, symbols: list[str], merged_path: str | None = None) -> dict[str, float | None]:
    """Opening prices on `today_date` for the symbols, as {"<symbol>_price": price}.

    A symbol with no data for that date is absent; one whose bar has no usable opening price is None.
    """
    wanted = set(symbols)
    results: dict[str, float | None] = {}
    for symbol, series in _price_documents(merged_path):
        if symbol not in wanted:
            continue
        bar = series.get(today_date)
        if isinstance(bar, dict):
            results[f"{symbol}_price"] = _number(bar.get("1. buy price"))
    return results


def get_yesterday_open_and_close_price(
    today_date: str, symbols: list[str], merged_path: str | None = None
) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """The previous trading day's opening and closing prices for the symbols: ({symbol_price: open}, {symbol_price: close}). None where unknown."""
    wanted = set(symbols)
    yesterday = get_yesterday_date(today_date, merged_path)
    opens: dict[str, float | None] = {}
    closes: dict[str, float | None] = {}
    for symbol, series in _price_documents(merged_path):
        if symbol not in wanted:
            continue
        bar = series.get(yesterday)
        open_price = close_price = None
        if isinstance(bar, dict):
            open_price, close_price = _number(bar.get("1. buy price")), _number(bar.get("4. sell price"))
            if open_price is None or close_price is None:
                open_price = close_price = None
        opens[f"{symbol}_price"] = open_price
        closes[f"{symbol}_price"] = close_price
    return opens, closes


def get_yesterday_profit(
    today_date: str,
    yesterday_buy_prices: dict[str, float | None],
    yesterday_sell_prices: dict[str, float | None],
    yesterday_init_position: dict[str, float],
) -> dict[str, float]:
    """The profit each holding made yesterday: (close - open) * shares held, 0.0 where a price or the holding is missing.

    Args:
        today_date: today's date (kept for the callers' signature; the prices already refer to yesterday).
        yesterday_buy_prices: {symbol_price: opening price}.
        yesterday_sell_prices: {symbol_price: closing price}.
        yesterday_init_position: {symbol: shares}.
    """
    profit: dict[str, float] = {}
    for symbol in all_nasdaq_100_symbols:
        key = f"{symbol}_price"
        buy, sell = yesterday_buy_prices.get(key), yesterday_sell_prices.get(key)
        shares = yesterday_init_position.get(symbol, 0.0)
        profit[symbol] = round((sell - buy) * shares, 4) if buy is not None and sell is not None and shares > 0 else 0.0
    return profit


def _positions_on(signature: str, date: str, default_id: int) -> tuple[dict[str, float], int]:
    """The position record with the highest id on `date`: (positions, id), or ({}, -1) when there is none."""
    path = position_file(signature)
    best_id = -1
    positions: dict[str, float] = {}
    if not path.exists():
        return positions, best_id
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict) and doc.get("date") == date:
                record_id = doc.get("id", default_id)
                if isinstance(record_id, int) and record_id > best_id:
                    best_id = record_id
                    positions = doc.get("positions", {})
    return positions, best_id


def get_today_init_position(today_date: str, signature: str) -> dict[str, float]:
    """The positions the agent starts today with: the last record (highest id) of the previous trading date; {} if there is none."""
    if not position_file(signature).exists():
        print(f"Position file {position_file(signature)} does not exist")
        return {}
    return _positions_on(signature, get_yesterday_date(today_date), 0)[0]


def get_latest_position(today_date: str, signature: str) -> tuple[dict[str, float], int]:
    """The latest position: the highest-id record of today, else of the previous trading date.

    Returns:
        (positions, id): ({}, -1) when the agent has no record.
    """
    if not position_file(signature).exists():
        return {}, -1
    positions, record_id = _positions_on(signature, today_date, -1)
    if record_id >= 0:
        return positions, record_id
    return _positions_on(signature, get_yesterday_date(today_date), -1)


def add_no_trade_record(today_date: str, signature: str) -> None:
    """Record that the agent did not trade today: carry the latest position forward as a new record.

    Raises ValueError when the agent has no position to carry forward (writing an empty one would break every later trade).
    """
    from tools.positions import append_position_record, position_lock

    with position_lock(signature):
        position, last_id = get_latest_position(today_date, signature)
        if not position:
            raise ValueError(f"no position to carry forward for {signature} on {today_date}")
        append_position_record(
            signature,
            {
                "date": today_date,
                "id": last_id + 1,
                "this_action": {"action": "no_trade", "symbol": "", "amount": 0},
                "positions": position,
            },
        )
