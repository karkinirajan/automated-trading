"""Buying and selling in the simulated account: the rules, and one function that applies them under a lock.

The agent is a language model calling `buy` and `sell` as tools, so every argument is untrusted: the amount must be a positive whole number
(a negative "purchase" used to *add* cash and subtract shares), the price must exist, and the whole read-check-write runs under one lock.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tools.positions import append_position_record, position_lock
from tools.price_tools import get_latest_position, get_open_prices

MAX_AMOUNT = 1_000_000_000  # shares in one order: far above anything real, small enough that price * amount cannot overflow a float's meaning
CASH = "CASH"
_EPSILON = 1e-9


class TradeError(Exception):
    """A trade the account must refuse. `payload` is the dict returned to the agent (it always has an "error" message)."""

    def __init__(self, message: str, **details: Any):
        super().__init__(message)
        self.payload: dict[str, Any] = {"error": message, **details}


def validate_amount(amount: object) -> int:
    """A whole number of shares from 1 to MAX_AMOUNT (not a bool, not a float, not zero, not negative)."""
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TradeError("Invalid amount: it must be a whole number of shares. This action will not be allowed.")
    if amount < 1 or amount > MAX_AMOUNT:
        raise TradeError(f"Invalid amount: it must be between 1 and {MAX_AMOUNT} shares. This action will not be allowed.")
    return amount


def _valid_price(price: object) -> float:
    if isinstance(price, bool) or not isinstance(price, (int, float)) or price != price or price <= 0 or price == float("inf"):
        raise TradeError("Price is not available for this symbol and date. This action will not be allowed.")
    return float(price)


def apply_buy(position: dict[str, Any], symbol: str, amount: int, price: float) -> dict[str, Any]:
    """The position after buying `amount` shares at `price`. Raises TradeError when the cash is not enough."""
    amount = validate_amount(amount)
    price = _valid_price(price)
    cost = price * amount
    cash = position.get(CASH, 0)
    cash_left = cash - cost
    if cash_left < -_EPSILON:
        raise TradeError("Insufficient cash! This action will not be allowed.", required_cash=cost, cash_available=cash)
    new_position = dict(position)
    new_position[CASH] = round(max(cash_left, 0.0), 6)
    new_position[symbol] = new_position.get(symbol, 0) + amount
    return new_position


def apply_sell(position: dict[str, Any], symbol: str, amount: int, price: float) -> dict[str, Any]:
    """The position after selling `amount` shares at `price`. Raises TradeError when the shares are not held."""
    amount = validate_amount(amount)
    price = _valid_price(price)
    held = position.get(symbol, 0)
    if symbol not in position:
        raise TradeError(f"No position for {symbol}! This action will not be allowed.")
    if held < amount:
        raise TradeError("Insufficient shares! This action will not be allowed.", have=held, want_to_sell=amount)
    new_position = dict(position)
    new_position[symbol] = held - amount
    new_position[CASH] = round(position.get(CASH, 0) + price * amount, 6)
    return new_position


_APPLY: dict[str, Callable[[dict[str, Any], str, int, float], dict[str, Any]]] = {"buy": apply_buy, "sell": apply_sell}


def execute_trade(
    action: str,
    symbol: str,
    amount: object,
    *,
    signature: str,
    today_date: str,
    merged_path: str | None = None,
) -> dict[str, Any]:
    """Run one buy or sell for an agent at today's opening price: read the latest position, check, and append the new one, all under one lock.

    Returns the new position (the symbols held and "CASH"), or {"error": ..., "symbol": ..., "date": ...}: a refused trade never raises to the agent
    and never changes the account.
    """
    base = {"symbol": symbol, "date": today_date}
    try:
        validate_amount(amount)
        with position_lock(signature):
            position, last_id = get_latest_position(today_date, signature)
            if not position or CASH not in position:
                raise TradeError("No account position found for this date. This action will not be allowed.")
            if symbol not in position and action == "buy":
                raise TradeError(f"Symbol {symbol} not found! This action will not be allowed.")
            prices = get_open_prices(today_date, [symbol], merged_path)
            if f"{symbol}_price" not in prices:
                raise TradeError(f"Symbol {symbol} not found! This action will not be allowed.")
            new_position = _APPLY[action](position, symbol, amount, prices[f"{symbol}_price"])  # type: ignore[arg-type]
            append_position_record(
                signature,
                {
                    "date": today_date,
                    "id": last_id + 1,
                    "this_action": {"action": action, "symbol": symbol, "amount": amount},
                    "positions": new_position,
                },
            )
        return new_position
    except TradeError as error:
        return {**error.payload, **base}
