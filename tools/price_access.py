"""What an agent may see of a price, given the simulated "today".

The arena replays history, so a model must not be able to read prices from after the moment it is trading: the full day (or hour) it is trading shows only
the open, earlier ones show everything, later ones are refused. The date, not the symbol, decides.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

DAILY_FORMAT = "%Y-%m-%d"
HOURLY_FORMAT = "%Y-%m-%d %H:%M:%S"

FULL = "full"
OPEN_ONLY = "open_only"
BLOCKED = "blocked"


def parse_moment(text: object) -> datetime | None:
    """A "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS" string as a datetime, or None."""
    if not isinstance(text, str):
        return None
    for fmt in (HOURLY_FORMAT, DAILY_FORMAT):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def visibility(query_date: str, today: str | None, *, hourly: bool) -> str:
    """FULL, OPEN_ONLY or BLOCKED for a price asked for on `query_date` while the simulated moment is `today`.

    A daily price for the current day is OPEN_ONLY, even when `today` carries an hour (the day is not over); an hourly price is OPEN_ONLY only for the
    current hour. Anything later is BLOCKED. With no usable `today` everything is BLOCKED: nothing can be served without knowing where the line is.
    """
    asked = parse_moment(query_date)
    now = parse_moment(today)
    if asked is None or now is None:
        return BLOCKED
    if hourly:
        if asked > now:
            return BLOCKED
        return OPEN_ONLY if asked == now else FULL
    if asked.date() > now.date():
        return BLOCKED
    return OPEN_ONLY if asked.date() == now.date() else FULL


def ohlcv(bar: dict[str, Any], view: str) -> dict[str, Any]:
    """The bar as the tool returns it: everything for FULL, only the open (with notes for the rest) for OPEN_ONLY."""
    if view == OPEN_ONLY:
        return {
            "open": bar.get("1. buy price"),
            "high": "You can not get the current high price",
            "low": "You can not get the current low price",
            "close": "You can not get the next close price",
            "volume": "You can not get the current volume",
        }
    return {
        "open": bar.get("1. buy price"),
        "high": bar.get("2. high"),
        "low": bar.get("3. low"),
        "close": bar.get("4. sell price"),
        "volume": bar.get("5. volume"),
    }


def lookup(series: dict[str, Any], symbol: str, date: str, today: str | None, *, hourly: bool) -> dict[str, Any]:
    """The tool's answer for one symbol and date: {"symbol", "date", "ohlcv"} or {"error", "symbol", "date"}."""
    base = {"symbol": symbol, "date": date}
    view = visibility(date, today, hourly=hourly)
    if view == BLOCKED:
        if parse_moment(today) is None:
            return {"error": "TODAY_DATE is not set, so no price can be served (look-ahead could not be prevented).", **base}
        return {"error": "Data for dates after the current time is not available.", **base}
    bar = series.get(date)
    if not isinstance(bar, dict):
        visible = sorted((d for d in series if visibility(d, today, hourly=hourly) != BLOCKED), reverse=True)[:5]
        return {
            "error": f"Data not found for date {date}. Please verify the date exists in data. Sample available dates: {visible}",
            **base,
        }
    return {**base, "ohlcv": ohlcv(bar, view)}
