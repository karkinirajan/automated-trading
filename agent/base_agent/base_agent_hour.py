"""
BaseAgent_Hour class - Trading agent for hour-level trading.

Same trading session and date-range loop as BaseAgent; only the list of moments to trade differs:
they are the timestamps present in the hourly price data rather than the weekdays of a calendar.
"""

from datetime import datetime

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from agent.base_agent.base_agent import BaseAgent
from tools.price_access import parse_moment
from tools.price_tools import get_price_timestamps

HOURLY_FORMAT = "%Y-%m-%d %H:%M:%S"


class BaseAgent_Hour(BaseAgent):
    """Trading agent for hour-level trading: it trades at every timestamp that has price data."""

    def get_trading_dates(self, init_date: str, end_date: str) -> list[str]:
        """
        Get the timestamps still to trade from the hourly price data.

        A new agent is registered with `init_date` as its opening moment, which is not traded. An agent that has
        already traded resumes after its last recorded moment (and never before `init_date`).

        Args:
            init_date: Start (YYYY-MM-DD HH:MM:SS)
            end_date: End (YYYY-MM-DD HH:MM:SS)

        Returns:
            Sorted timestamps within the range that have price data

        Raises:
            ValueError: when the dates are not both in YYYY-MM-DD HH:MM:SS format
        """
        if (" " in init_date) != (" " in end_date):
            raise ValueError("init_date and end_date must have the same time format")
        if " " not in init_date:
            raise ValueError("Only support hour-level trading. Please use YYYY-MM-DD HH:MM:SS format.")
        init_dt = datetime.strptime(init_date, HOURLY_FORMAT)
        end_dt = datetime.strptime(end_date, HOURLY_FORMAT)

        moments = {stamp: parse_moment(stamp) for stamp in get_price_timestamps() if " " in stamp}
        moments = {stamp: moment for stamp, moment in moments.items() if moment is not None}
        if not moments:
            return []

        if self._last_recorded_moment() is None:
            self.register_agent(init_date)
        last = self._last_recorded_moment()
        assert last is not None  # registered just above
        return sorted(stamp for stamp, moment in moments.items() if moment > last and init_dt <= moment <= end_dt)

    def __str__(self) -> str:
        return f"BaseAgent_Hour(signature='{self.signature}', basemodel='{self.basemodel}', stocks={len(self.stock_symbols)})"

    def __repr__(self) -> str:
        return self.__str__()
