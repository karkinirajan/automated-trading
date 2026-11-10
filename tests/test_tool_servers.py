"""The four MCP tool servers, called the way an agent calls them: through a FastMCP client, in memory."""

import asyncio
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from agent_tools import tool_get_price_local as price_tool
from agent_tools import tool_math as math_tool
from agent_tools import tool_trade as trade_tool
from tests.helpers import bar, read_positions, write_positions, write_prices
from tools.general_tools import get_config_value
from tools.server import run_server


def call(server, tool, **arguments):
    async def go():
        async with Client(server) as client:
            result = await client.call_tool(tool, arguments)
            return result.data

    return asyncio.run(go())


def names(server):
    async def go():
        async with Client(server) as client:
            return sorted(t.name for t in await client.list_tools())

    return asyncio.run(go())


@pytest.fixture()
def market(project, agent, settings):
    write_positions(agent, [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 1000.0, "AAPL": 0, "MSFT": 5}}])
    write_prices(
        project,
        {
            "AAPL": {"2025-10-01": bar(99, 100), "2025-10-02": bar(100, 105), "2025-10-03": bar(110, 120)},
            "MSFT": {"2025-10-01": bar(199, 200), "2025-10-02": bar(200, 205), "2025-10-03": bar(210, 220)},
        },
    )
    settings(today="2025-10-02")
    return agent


class TestMath:
    def test_the_tools(self):
        assert names(math_tool.mcp) == ["add", "multiply"]

    def test_add_and_multiply(self):
        assert call(math_tool.mcp, "add", a=1.5, b=2) == 3.5
        assert call(math_tool.mcp, "multiply", a=3, b=-2.5) == -7.5

    def test_the_port(self, monkeypatch):
        started = {}
        monkeypatch.setattr(math_tool.mcp, "run", lambda **kw: started.update(kw))
        run_server(math_tool.mcp, "MATH_HTTP_PORT", 8000)
        assert started["port"] == 8000


class TestTrade:
    def test_the_tools(self):
        assert names(trade_tool.mcp) == ["buy", "sell"]

    def test_a_buy_through_the_tool(self, market):
        result = call(trade_tool.mcp, "buy", symbol="AAPL", amount=3)
        assert result == {"CASH": 700.0, "AAPL": 3, "MSFT": 5}
        assert read_positions(market)[-1]["this_action"] == {"action": "buy", "symbol": "AAPL", "amount": 3}

    def test_the_trade_flag_is_set_only_when_a_trade_happened(self, market):
        assert not get_config_value("IF_TRADE")
        call(trade_tool.mcp, "buy", symbol="AAPL", amount=10_000)  # far too much
        assert not get_config_value("IF_TRADE")
        call(trade_tool.mcp, "buy", symbol="AAPL", amount=1)
        assert get_config_value("IF_TRADE") is True

    def test_a_sell_through_the_tool(self, market):
        assert call(trade_tool.mcp, "sell", symbol="MSFT", amount=5) == {"CASH": 2000.0, "AAPL": 0, "MSFT": 0}

    def test_a_negative_amount_is_refused_and_nothing_is_written(self, market):
        before = (market / "position" / "position.jsonl").read_text()
        result = call(trade_tool.mcp, "buy", symbol="AAPL", amount=-1000)
        assert "error" in result and "Invalid amount" in result["error"]
        assert (market / "position" / "position.jsonl").read_text() == before

    def test_a_fractional_amount_is_refused_by_the_tool_schema(self, market):
        with pytest.raises(ToolError):
            call(trade_tool.mcp, "buy", symbol="AAPL", amount=1.5)

    def test_without_a_signature_the_tool_fails_loudly(self, project, monkeypatch):
        monkeypatch.delenv("SIGNATURE", raising=False)
        monkeypatch.setenv("RUNTIME_ENV_PATH", str(project / "nothing.json"))
        with pytest.raises(ToolError, match="SIGNATURE"):
            call(trade_tool.mcp, "buy", symbol="AAPL", amount=1)

    def test_without_a_date_the_tool_fails_loudly(self, project, settings):
        settings(today=None)
        with pytest.raises(ToolError, match="TODAY_DATE"):
            call(trade_tool.mcp, "buy", symbol="AAPL", amount=1)

    def test_the_port(self, monkeypatch):
        started = {}
        monkeypatch.setattr(trade_tool.mcp, "run", lambda **kw: started.update(kw))
        monkeypatch.setenv("TRADE_HTTP_PORT", "9002")
        run_server(trade_tool.mcp, "TRADE_HTTP_PORT", 8002)
        assert started == {"transport": "streamable-http", "host": "127.0.0.1", "port": 9002}


class TestPrices:
    def test_the_tool(self):
        assert names(price_tool.mcp) == ["get_price_local"]

    def test_yesterday_is_fully_visible(self, market):
        out = call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-01")
        assert out["ohlcv"] == {"open": "99", "high": "101", "low": "99", "close": "100", "volume": "1000"}

    def test_today_shows_only_the_open(self, market):
        out = call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-02")
        assert out["ohlcv"]["open"] == "100"
        assert out["ohlcv"]["close"] == "You can not get the next close price"
        assert "105" not in json.dumps(out)

    def test_tomorrow_is_not_available(self, market):
        out = call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-03")
        assert "error" in out and "ohlcv" not in out
        assert "120" not in json.dumps(out) and "110" not in json.dumps(out)

    def test_a_missing_day_does_not_name_future_dates(self, market):
        out = call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-09-15")
        assert "2025-10-03" not in out["error"] and "2025-10-02" in out["error"]

    def test_no_clock_no_prices(self, project, settings):
        write_prices(project, {"AAPL": {"2025-10-01": bar(1, 2)}})
        settings(today=None, signature=None)
        out = call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-01")
        assert "TODAY_DATE is not set" in out["error"]

    def test_an_unknown_symbol(self, market):
        assert "No records found for stock ZZZ" in call(price_tool.mcp, "get_price_local", symbol="ZZZ", date="2025-10-01")["error"]

    def test_a_bad_date_format(self, market):
        assert call(price_tool.mcp, "get_price_local", symbol="AAPL", date="10/01/2025")["error"] == "date must be in YYYY-MM-DD format"

    def test_a_date_that_is_not_a_date(self, market):
        assert "YYYY-MM-DD" in call(price_tool.mcp, "get_price_local", symbol="AAPL", date="soon")["error"]

    def test_the_hourly_format_is_chosen_by_the_date(self, project, settings):
        write_prices(project, {"AAPL": {"2025-10-02 10:00:00": bar(1, 2), "2025-10-02 11:00:00": bar(3, 4), "2025-10-02 12:00:00": bar(5, 6)}}, hourly=True)
        settings(today="2025-10-02 11:00:00", signature=None)
        assert call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-02 10:00:00")["ohlcv"]["close"] == "2"
        assert call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-02 11:00:00")["ohlcv"]["close"] == "You can not get the next close price"
        assert "error" in call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-02 12:00:00")

    def test_a_daily_date_on_hourly_data_finds_nothing(self, project, settings):
        write_prices(project, {"AAPL": {"2025-10-02 10:00:00": bar(1, 2)}}, hourly=True)
        settings(today="2025-10-03", signature=None)
        assert "No records found" in call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-02")["error"]

    def test_an_hourly_date_in_daily_format_is_refused(self, market):
        assert "YYYY-MM-DD HH:MM:SS" in price_tool.get_price_local_hourly("AAPL", "2025-10-01")["error"]

    def test_the_two_helpers(self, market):
        assert price_tool.get_price_local_daily("AAPL", "2025-10-01")["ohlcv"]["close"] == "100"
        assert "error" in price_tool.get_price_local_daily("AAPL", "2025-10-03")

    def test_a_date_with_a_t_is_treated_as_hourly(self, market):
        assert "YYYY-MM-DD HH:MM:SS" in call(price_tool.mcp, "get_price_local", symbol="AAPL", date="2025-10-01T10:00:00")["error"]

    def test_the_port(self, monkeypatch):
        started = {}
        monkeypatch.setattr(price_tool.mcp, "run", lambda **kw: started.update(kw))
        run_server(price_tool.mcp, "GETPRICE_HTTP_PORT", 8003)
        assert started["port"] == 8003


class TestRunServer:
    class Recorder:
        def __init__(self):
            self.kw = None

        def run(self, **kw):
            self.kw = kw

    def test_it_listens_on_loopback_by_default(self):
        recorder = self.Recorder()
        run_server(recorder, "SOME_PORT", 8123)
        assert recorder.kw == {"transport": "streamable-http", "host": "127.0.0.1", "port": 8123}

    def test_the_host_and_port_can_be_set(self, monkeypatch):
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("SOME_PORT", "9999")
        recorder = self.Recorder()
        run_server(recorder, "SOME_PORT", 8123)
        assert recorder.kw["host"] == "0.0.0.0" and recorder.kw["port"] == 9999

    def test_a_port_that_is_not_a_number_is_an_error(self, monkeypatch):
        monkeypatch.setenv("SOME_PORT", "http")
        with pytest.raises(ValueError):
            run_server(self.Recorder(), "SOME_PORT", 8123)
