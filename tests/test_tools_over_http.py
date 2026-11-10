"""The trade and price servers over real HTTP on the loopback address, called through the agent's own MCP connection settings.

This is the wire the language model uses, minus the model: two agents share one set of servers, and each call must be served for the agent that made it.
"""

import asyncio
import json
import socket
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.base_agent.base_agent import BaseAgent
from agent_tools import tool_get_price_local as price_tool
from agent_tools import tool_jina_search as search_tool
from agent_tools import tool_trade as trade_tool
from tests.helpers import bar, read_positions, write_positions, write_prices
from tools.agent_context import AGENT_HEADER
from tools.general_tools import write_config_value


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def serve(mcp, port):
    server = uvicorn.Server(uvicorn.Config(mcp.http_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "the test server did not start"
        time.sleep(0.02)
    try:
        yield
    finally:
        server.should_exit = True
        thread.join(10)


def payload(result):
    """The dict a tool returned, from either client's result shape."""
    if hasattr(result, "data"):
        return result.data
    if isinstance(result, str):
        return json.loads(result)
    if isinstance(result, list):
        return json.loads(result[0]["text"])
    return result


@pytest.fixture()
def world(project):
    """Two funded agents on different simulated days, prices for three days, and a server-side environment that names a third, unrelated agent."""
    write_prices(
        project,
        {
            "AAPL": {"2025-10-01": bar(100, 101), "2025-10-02": bar(110, 111), "2025-10-03": bar(120, 121)},
        },
    )
    for name, today in (("alice", "2025-10-02"), ("bob", "2025-10-03")):
        folder = project / "agent_data" / name
        records = [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 1000.0, "AAPL": 0}}]
        if name == "bob":  # bob's day is the 3rd: the 2nd is already behind him, with its own (unchanged) record
            records.append({"date": "2025-10-02", "id": 1, "positions": {"CASH": 1000.0, "AAPL": 0}})
        write_positions(folder, records)
        (folder / ".runtime_env.json").write_text(json.dumps({"TODAY_DATE": today, "IF_TRADE": False}))
    # what the servers' own environment says: another agent, another day
    write_config_value("TODAY_DATE", "1999-01-01")
    write_config_value("SIGNATURE", "wrong-agent")
    return project


@pytest.fixture()
def servers(world):
    trade_port, price_port = free_port(), free_port()
    with serve(trade_tool.mcp, trade_port), serve(price_tool.mcp, price_port):
        yield {
            "trade": {"transport": "streamable_http", "url": f"http://127.0.0.1:{trade_port}/mcp"},
            "stock_local": {"transport": "streamable_http", "url": f"http://127.0.0.1:{price_port}/mcp"},
        }


def tools_for(signature, connections):
    """The langchain tools of one agent, loaded the way BaseAgent.initialize loads them."""
    agent = BaseAgent(signature=signature, basemodel="m", mcp_config=connections, openai_api_key="k")

    async def load():
        return {t.name: t for t in await MultiServerMCPClient(agent.mcp_config).get_tools()}

    return agent, asyncio.run(load())


def call(tool, **arguments):
    return payload(asyncio.run(tool.ainvoke(arguments)))


class TestAgentsShareTheServers:
    def test_the_agent_names_itself_on_every_connection(self, servers):
        agent = BaseAgent(signature="alice", basemodel="m", mcp_config=servers, openai_api_key="k")
        assert all(c["headers"] == {AGENT_HEADER: "alice"} for c in agent.mcp_config.values())
        assert "headers" not in servers["trade"]  # the caller's own settings are not changed

    def test_existing_headers_are_kept(self):
        agent = BaseAgent(signature="alice", basemodel="m", mcp_config={"x": {"transport": "streamable_http", "url": "u", "headers": {"X-Other": "1"}}}, openai_api_key="k")
        assert agent.mcp_config["x"]["headers"] == {"X-Other": "1", AGENT_HEADER: "alice"}

    def test_each_agents_order_is_booked_to_its_own_account_at_its_own_days_price(self, servers, world):
        _, alice = tools_for("alice", servers)
        _, bob = tools_for("bob", servers)
        assert call(alice["buy"], symbol="AAPL", amount=2) == {"CASH": 780.0, "AAPL": 2}  # the 2025-10-02 open, 110
        assert call(bob["buy"], symbol="AAPL", amount=1) == {"CASH": 880.0, "AAPL": 1}  # the 2025-10-03 open, 120
        assert read_positions(world / "agent_data" / "alice")[-1]["positions"] == {"CASH": 780.0, "AAPL": 2}
        assert read_positions(world / "agent_data" / "bob")[-1]["positions"] == {"CASH": 880.0, "AAPL": 1}
        assert read_positions(world / "agent_data" / "alice")[-1]["date"] == "2025-10-02"
        assert read_positions(world / "agent_data" / "bob")[-1]["date"] == "2025-10-03"
        assert not (world / "agent_data" / "wrong-agent").exists()

    def test_the_traded_flag_is_set_in_the_callers_file_only(self, servers, world):
        _, alice = tools_for("alice", servers)
        call(alice["buy"], symbol="AAPL", amount=1)
        assert json.loads((world / "agent_data" / "alice" / ".runtime_env.json").read_text())["IF_TRADE"] is True
        assert json.loads((world / "agent_data" / "bob" / ".runtime_env.json").read_text())["IF_TRADE"] is False

    def test_a_refused_order_leaves_the_account_alone(self, servers, world):
        _, alice = tools_for("alice", servers)
        before = (world / "agent_data" / "alice" / "position" / "position.jsonl").read_text()
        assert "error" in call(alice["buy"], symbol="AAPL", amount=-5)
        assert (world / "agent_data" / "alice" / "position" / "position.jsonl").read_text() == before

    def test_each_agent_sees_prices_up_to_its_own_day_only(self, servers):
        _, alice = tools_for("alice", servers)
        _, bob = tools_for("bob", servers)
        price = lambda tool, date: call(tool["get_price_local"], symbol="AAPL", date=date)  # noqa: E731
        assert "error" in price(alice, "2025-10-03")  # tomorrow, for alice
        assert price(bob, "2025-10-03")["ohlcv"]["close"] == "You can not get the next close price"  # today, for bob
        assert price(alice, "2025-10-01")["ohlcv"]["close"] == "101"
        assert price(bob, "2025-10-02")["ohlcv"]["close"] == "111"  # alice's today is bob's past
        assert price(alice, "2025-10-02")["ohlcv"]["close"] == "You can not get the next close price"

    def test_concurrent_agents_do_not_mix_up_their_calls(self, servers, world):
        _, alice = tools_for("alice", servers)
        _, bob = tools_for("bob", servers)

        async def both():
            return await asyncio.gather(*[(alice if i % 2 == 0 else bob)["buy"].ainvoke({"symbol": "AAPL", "amount": 1}) for i in range(8)])

        asyncio.run(both())
        assert read_positions(world / "agent_data" / "alice")[-1]["positions"] == {"CASH": 1000.0 - 4 * 110, "AAPL": 4}
        assert read_positions(world / "agent_data" / "bob")[-1]["positions"] == {"CASH": 1000.0 - 4 * 120, "AAPL": 4}


class FakeJina:
    """Jina's search returns two pages; its reader returns the page asked for."""

    def __init__(self):
        self.status_code = 200
        self.payload = None

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def fake_jina_get(url, **kwargs):
    response = FakeJina()
    if url.startswith("https://s.jina.ai"):
        response.payload = {
            "data": [
                {"url": "https://later.example/page", "date": "2025-10-02T12:00:00Z"},  # after alice's day starts, before bob's
                {"url": "https://earlier.example/page", "date": "2025-10-01T08:00:00Z"},
            ]
        }
    else:
        page = url.removeprefix("https://r.jina.ai/")
        response.payload = {"data": {"url": page, "title": "T", "description": "D", "content": "C", "publishedTime": "x"}}
    return response


class TestSearchOverHttp:
    def test_each_agent_is_shown_only_what_was_published_before_its_own_day(self, world, monkeypatch):
        monkeypatch.setenv("JINA_API_KEY", "k")
        monkeypatch.setattr(search_tool.requests, "get", fake_jina_get)
        port = free_port()
        connections = {"search": {"transport": "streamable_http", "url": f"http://127.0.0.1:{port}/mcp"}}
        with serve(search_tool.mcp, port):
            _, alice = tools_for("alice", connections)
            _, bob = tools_for("bob", connections)
            alice_text = payload_text(asyncio.run(alice["get_information"].ainvoke({"query": "q"})))
            bob_text = payload_text(asyncio.run(bob["get_information"].ainvoke({"query": "q"})))
        assert "URL: https://earlier.example/page" in alice_text and "later.example" not in alice_text
        assert "URL: https://later.example/page" in bob_text


def payload_text(result):
    if isinstance(result, list):
        return result[0]["text"]
    return result


class TestWithoutOrWithABadHeader:
    def client(self, url, **headers):
        return Client(StreamableHttpTransport(url, headers=headers))

    def test_a_request_without_the_header_is_served_from_the_servers_own_settings(self, servers, world):
        before = {name: read_positions(world / "agent_data" / name) for name in ("alice", "bob")}

        async def go():
            async with self.client(servers["trade"]["url"]) as client:
                return (await client.call_tool("buy", {"symbol": "AAPL", "amount": 1})).data

        result = asyncio.run(go())
        assert "error" in result and "No account position" in result["error"]  # "wrong-agent" has no account; alice and bob were not touched
        assert {name: read_positions(world / "agent_data" / name) for name in ("alice", "bob")} == before

    @pytest.mark.parametrize("value", ["../../etc", "a/b", ".hidden"])
    def test_an_unsafe_signature_header_is_an_error(self, servers, value):
        async def go():
            async with self.client(servers["trade"]["url"], **{AGENT_HEADER: value}) as client:
                await client.call_tool("buy", {"symbol": "AAPL", "amount": 1})

        with pytest.raises(ToolError, match="unsafe agent signature"):
            asyncio.run(go())

    def test_an_agent_that_does_not_exist_cannot_trade_or_see_prices(self, servers, world):
        async def go():
            async with self.client(servers["trade"]["url"], **{AGENT_HEADER: "nobody"}) as trade, self.client(servers["stock_local"]["url"], **{AGENT_HEADER: "nobody"}) as prices:
                with pytest.raises(ToolError, match="TODAY_DATE"):
                    await trade.call_tool("buy", {"symbol": "AAPL", "amount": 1})
                return (await prices.call_tool("get_price_local", {"symbol": "AAPL", "date": "2025-10-01"})).data

        assert "TODAY_DATE is not set" in asyncio.run(go())["error"]  # no clock for this agent: nothing is served
        assert not (world / "agent_data" / "nobody").exists()
