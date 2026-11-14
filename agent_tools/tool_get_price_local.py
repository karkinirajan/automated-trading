import os
import sys
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("LocalPrices")

# Ensure project root is on sys.path for absolute imports like `tools.*`
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tools.agent_context import calling_agent  # noqa: E402
from tools.general_tools import get_config_value  # noqa: E402
from tools.price_access import lookup, parse_moment  # noqa: E402
from tools.price_tools import _price_documents  # noqa: E402
from tools.server import run_server  # noqa: E402


def _series_for(symbol: str, hourly: bool) -> dict[str, Any] | None:
    """The time series of one symbol in the merged price file (its daily bars, or its hourly ones), or None."""
    for found, series in _price_documents(None, "(60min)" if hourly else "(Daily)"):
        if found == symbol:
            return series
    return None


def _get(symbol: str, date: str, hourly: bool) -> dict[str, Any]:
    if parse_moment(date) is None or (" " in date) != hourly:
        message = "date must be in YYYY-MM-DD HH:MM:SS format" if hourly else "date must be in YYYY-MM-DD format"
        return {"error": message, "symbol": symbol, "date": date}
    series = _series_for(symbol, hourly)
    if series is None:
        return {"error": f"No records found for stock {symbol} in local data", "symbol": symbol, "date": date}
    return lookup(series, symbol, date, get_config_value("TODAY_DATE"), hourly=hourly)


@mcp.tool()
def get_price_local(symbol: str, date: str) -> dict[str, Any]:
    """Read OHLCV data for specified stock and date. Get historical information for specified stock.

    Automatically detects date format and calls appropriate function:
    - Daily data: YYYY-MM-DD format (e.g., '2025-10-30')
    - Hourly data: YYYY-MM-DD HH:MM:SS format (e.g., '2025-10-30 14:30:00')

    Only the past is available: the open of the current day (or hour) is shown, the rest of it is not, and later dates are refused.

    Args:
        symbol: Stock symbol, e.g. 'IBM' or '600243.SHH'.
        date: Date in 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' format. Based on your current time format.

    Returns:
        Dictionary containing symbol, date and ohlcv data.
    """
    with calling_agent():
        return _get(symbol, date, hourly=(" " in date or "T" in date))


def get_price_local_daily(symbol: str, date: str) -> dict[str, Any]:
    """Daily OHLCV for a symbol and 'YYYY-MM-DD' date (see get_price_local)."""
    return _get(symbol, date, hourly=False)


def get_price_local_hourly(symbol: str, date: str) -> dict[str, Any]:
    """Hourly OHLCV for a symbol and 'YYYY-MM-DD HH:MM:SS' date (see get_price_local)."""
    return _get(symbol, date, hourly=True)


if __name__ == "__main__":
    run_server(mcp, "GETPRICE_HTTP_PORT", 8003)
