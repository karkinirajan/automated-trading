import os
import sys
from typing import Any

from fastmcp import FastMCP

# Add project root directory to Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
from tools.agent_context import calling_agent  # noqa: E402
from tools.general_tools import get_config_value, write_config_value  # noqa: E402
from tools.server import run_server  # noqa: E402
from tools.trading import execute_trade  # noqa: E402

mcp = FastMCP("TradeTools")


def _trade(action: str, symbol: str, amount: int) -> dict[str, Any]:
    """Run one order for the current agent and day; record that the agent traded when it went through."""
    with calling_agent() as caller:
        signature = caller or get_config_value("SIGNATURE")
        if signature is None:
            raise ValueError("SIGNATURE environment variable is not set")
        today_date = get_config_value("TODAY_DATE")
        if not today_date:
            raise ValueError("TODAY_DATE is not set")
        result = execute_trade(action, symbol, amount, signature=signature, today_date=today_date)
        if "error" not in result:
            write_config_value("IF_TRADE", True)
        return result


@mcp.tool()
def buy(symbol: str, amount: int) -> dict[str, Any]:
    """
    Buy stock function

    This function simulates stock buying operations at today's opening price:
    1. Get the current position
    2. Get the stock's opening price for the day
    3. Validate the order (a positive whole number of shares, enough cash)
    4. Update the position (more shares, less cash)
    5. Record the transaction

    Args:
        symbol: Stock symbol, such as "AAPL", "MSFT", etc.
        amount: Buy quantity, a positive whole number of shares

    Returns:
        Success: the new position (the stock quantities and the cash balance).
        Failure: {"error": error message, ...}; the account is unchanged.

    Example:
        >>> buy("AAPL", 10)  # {"AAPL": 110, "MSFT": 5, "CASH": 5000.0, ...}
    """
    return _trade("buy", symbol, amount)


@mcp.tool()
def sell(symbol: str, amount: int) -> dict[str, Any]:
    """
    Sell stock function

    This function simulates stock selling operations at today's opening price:
    1. Get the current position
    2. Get the stock's opening price for the day
    3. Validate the order (a positive whole number of shares, enough shares held)
    4. Update the position (fewer shares, more cash)
    5. Record the transaction

    Args:
        symbol: Stock symbol, such as "AAPL", "MSFT", etc.
        amount: Sell quantity, a positive whole number of shares

    Returns:
        Success: the new position (the stock quantities and the cash balance).
        Failure: {"error": error message, ...}; the account is unchanged.

    Example:
        >>> sell("AAPL", 10)  # {"AAPL": 90, "MSFT": 5, "CASH": 15000.0, ...}
    """
    return _trade("sell", symbol, amount)


if __name__ == "__main__":
    run_server(mcp, "TRADE_HTTP_PORT", 8002)
