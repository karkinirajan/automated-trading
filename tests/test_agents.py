"""BaseAgent and BaseAgent_Hour with the model and the MCP client replaced by fakes."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from agent.base_agent import base_agent as base_module
from agent.base_agent.base_agent import BaseAgent
from agent.base_agent.base_agent_hour import BaseAgent_Hour
from prompts.agent_prompt import STOP_SIGNAL
from tests.helpers import bar, read_positions, write_positions, write_prices
from tools.general_tools import get_config_value, write_config_value

SYMBOLS = ["AAPL", "MSFT"]


def make(cls=BaseAgent, **kwargs):
    defaults = dict(signature="bot", basemodel="m", stock_symbols=SYMBOLS, openai_api_key="k", openai_base_url="http://x", init_date="2025-10-01", base_delay=0)
    return cls(**{**defaults, **kwargs})


@pytest.fixture()
def agent_root(project, monkeypatch):
    """The agents keep their files under log_path; point it at the private project's agent_data."""
    return project / "agent_data"


class TestConstruction:
    def test_defaults(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        monkeypatch.setenv("OPENAI_API_BASE", "http://env")
        agent = BaseAgent(signature="bot", basemodel="m")
        assert agent.openai_api_key == "env-key" and agent.openai_base_url == "http://env"
        assert agent.max_steps == 10 and agent.max_retries == 3 and agent.initial_cash == 10000.0
        assert len(agent.stock_symbols) > 90 and agent.base_log_path == "./data/agent_data"

    def test_explicit_settings_beat_the_environment(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        agent = make(openai_api_key="mine")
        assert agent.openai_api_key == "mine"

    def test_an_unsafe_signature_is_refused(self):
        with pytest.raises(ValueError):
            make(signature="../escape")

    def test_the_default_mcp_ports_come_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("TRADE_HTTP_PORT", "9002")
        config = make()._get_default_mcp_config()
        assert set(config) == {"math", "stock_local", "search", "trade"}
        assert config["trade"] == {"transport": "streamable_http", "url": "http://127.0.0.1:9002/mcp"}
        assert config["math"]["url"] == "http://127.0.0.1:8000/mcp" and config["search"]["url"].endswith(":8001/mcp") and config["stock_local"]["url"].endswith(":8003/mcp")

    def test_str(self):
        assert str(make()) == "BaseAgent(signature='bot', basemodel='m', stocks=2)"
        assert repr(make(cls=BaseAgent_Hour)) == "BaseAgent_Hour(signature='bot', basemodel='m', stocks=2)"


class TestInitialize:
    def test_without_a_key_it_refuses(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        agent = make(openai_api_key=None)
        with pytest.raises(ValueError, match="OpenAI API key not set"):
            asyncio.run(agent.initialize())

    def test_it_connects_and_builds_the_model(self, monkeypatch):
        seen = {}

        class FakeClient:
            def __init__(self, config):
                seen["config"] = config

            async def get_tools(self):
                return ["tool-a", "tool-b"]

        monkeypatch.setattr(base_module, "MultiServerMCPClient", FakeClient)
        agent = make()
        asyncio.run(agent.initialize())
        assert agent.tools == ["tool-a", "tool-b"] and seen["config"] == agent.mcp_config
        assert agent.model.model_name == "m" and agent.model.max_retries == 3

    def test_no_tools_is_a_warning_not_an_error(self, monkeypatch, capsys):
        class FakeClient:
            def __init__(self, config):
                pass

            async def get_tools(self):
                return []

        monkeypatch.setattr(base_module, "MultiServerMCPClient", FakeClient)
        asyncio.run(make().initialize())
        assert "No MCP tools loaded" in capsys.readouterr().out

    def test_an_unreachable_mcp_server_is_a_clear_error(self, monkeypatch):
        class FakeClient:
            def __init__(self, config):
                pass

            async def get_tools(self):
                raise ConnectionError("refused")

        monkeypatch.setattr(base_module, "MultiServerMCPClient", FakeClient)
        with pytest.raises(RuntimeError, match="Failed to initialize MCP client: refused") as exc:
            asyncio.run(make().initialize())
        assert isinstance(exc.value.__cause__, ConnectionError)

    def test_a_model_that_cannot_be_built_is_a_clear_error(self, monkeypatch):
        class FakeClient:
            def __init__(self, config):
                pass

            async def get_tools(self):
                return ["t"]

        def broken(**kwargs):
            raise TypeError("bad model")

        monkeypatch.setattr(base_module, "MultiServerMCPClient", FakeClient)
        monkeypatch.setattr(base_module, "ChatOpenAI", broken)
        with pytest.raises(RuntimeError, match="Failed to initialize AI model: bad model"):
            asyncio.run(make().initialize())


class TestRegistration:
    def test_a_new_agent_gets_its_starting_position(self, agent_root):
        agent = make(log_path=str(agent_root), initial_cash=500.0)
        agent.register_agent()
        assert read_positions(agent_root / "bot") == [{"date": "2025-10-01", "id": 0, "positions": {"AAPL": 0, "MSFT": 0, "CASH": 500.0}}]

    def test_the_opening_date_can_be_given(self, agent_root):
        make(log_path=str(agent_root)).register_agent("2025-10-05")
        assert read_positions(agent_root / "bot")[0]["date"] == "2025-10-05"

    def test_an_existing_position_is_left_alone(self, agent_root, capsys):
        write_positions(agent_root / "bot", [{"date": "2025-10-02", "id": 7, "positions": {"CASH": 1.0}}])
        make(log_path=str(agent_root)).register_agent()
        assert read_positions(agent_root / "bot") == [{"date": "2025-10-02", "id": 7, "positions": {"CASH": 1.0}}]
        assert "skipping registration" in capsys.readouterr().out

    def test_an_empty_position_file_is_registered_again(self, agent_root):
        path = agent_root / "bot" / "position" / "position.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n")
        make(log_path=str(agent_root)).register_agent()
        assert len(read_positions(agent_root / "bot")) == 1


class TestLastRecordedMoment:
    def test_none_without_a_file(self, agent_root):
        assert make(log_path=str(agent_root))._last_recorded_moment() is None

    def test_the_latest_date_whatever_the_order_and_blank_lines(self, agent_root):
        path = agent_root / "bot" / "position" / "position.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"date": "2025-10-03", "id": 1}\n\n{"date": "2025-10-01", "id": 0}\n{"date": "2025-10-02 10:00:00", "id": 2}\n')
        assert make(log_path=str(agent_root))._last_recorded_moment().isoformat() == "2025-10-03T00:00:00"

    def test_a_damaged_record_is_loud(self, agent_root):
        path = agent_root / "bot" / "position" / "position.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('{"date": "soon", "id": 1}\n')
        with pytest.raises(ValueError, match="Unreadable date"):
            make(log_path=str(agent_root))._last_recorded_moment()
        path.write_text("not json\n")
        with pytest.raises(json.JSONDecodeError):
            make(log_path=str(agent_root))._last_recorded_moment()


class TestTradingDates:
    def test_a_new_agent_is_registered_and_trades_the_weekdays_after_its_opening_date(self, agent_root):
        agent = make(log_path=str(agent_root))
        # 2025-10-01 is a Wednesday
        assert agent.get_trading_dates("2025-10-01", "2025-10-08") == ["2025-10-02", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08"]
        assert read_positions(agent_root / "bot")[0]["date"] == "2025-10-01"

    def test_the_opening_date_of_the_file_follows_the_start_of_the_range_not_the_constructor(self, agent_root):
        agent = make(log_path=str(agent_root), init_date="2025-10-13")
        assert agent.get_trading_dates("2025-10-01", "2025-10-03") == ["2025-10-02", "2025-10-03"]
        assert read_positions(agent_root / "bot")[0]["date"] == "2025-10-01"

    def test_a_resumed_agent_continues_after_its_last_record(self, agent_root):
        write_positions(agent_root / "bot", [{"date": "2025-10-03", "id": 0, "positions": {"CASH": 1.0}}])
        assert make(log_path=str(agent_root)).get_trading_dates("2025-10-01", "2025-10-08") == ["2025-10-06", "2025-10-07", "2025-10-08"]  # Friday the 3rd was recorded; the weekend is skipped

    def test_nothing_to_do_when_the_end_is_not_after_the_last_record(self, agent_root):
        write_positions(agent_root / "bot", [{"date": "2025-10-08", "id": 0, "positions": {"CASH": 1.0}}])
        agent = make(log_path=str(agent_root))
        assert agent.get_trading_dates("2025-10-01", "2025-10-08") == []
        assert agent.get_trading_dates("2025-10-01", "2025-10-02") == []

    def test_weekends_are_skipped(self, agent_root):
        assert make(log_path=str(agent_root)).get_trading_dates("2025-10-03", "2025-10-06") == ["2025-10-06"]

    def test_a_bad_end_date(self, agent_root):
        with pytest.raises(ValueError):
            make(log_path=str(agent_root)).get_trading_dates("2025-10-01", "10/08/2025")


class TestHourlyTradingDates:
    @pytest.fixture()
    def hourly(self, project, agent_root):
        stamps = ["2025-10-01 10:00:00", "2025-10-01 11:00:00", "2025-10-01 12:00:00", "2025-10-02 10:00:00", "2025-10-02 11:00:00"]
        write_prices(project, {"AAPL": {s: bar(1) for s in stamps}, "MSFT": {s: bar(2) for s in stamps[1:]}}, hourly=True)
        return make(cls=BaseAgent_Hour, log_path=str(agent_root))

    def test_a_new_agent_trades_every_timestamp_after_its_opening_moment(self, hourly, agent_root):
        assert hourly.get_trading_dates("2025-10-01 10:00:00", "2025-10-02 11:00:00") == [
            "2025-10-01 11:00:00",
            "2025-10-01 12:00:00",
            "2025-10-02 10:00:00",
            "2025-10-02 11:00:00",
        ]
        assert read_positions(agent_root / "bot")[0]["date"] == "2025-10-01 10:00:00"

    def test_an_opening_moment_that_is_not_a_bar_does_not_cost_the_next_bar(self, hourly):
        # the old code always dropped the first timestamp; here 10:30 is not one, so 11:00 is traded
        assert hourly.get_trading_dates("2025-10-01 10:30:00", "2025-10-01 12:00:00") == ["2025-10-01 11:00:00", "2025-10-01 12:00:00"]

    def test_the_end_is_inclusive(self, hourly):
        assert hourly.get_trading_dates("2025-10-01 10:00:00", "2025-10-01 11:00:00") == ["2025-10-01 11:00:00"]

    def test_a_resumed_agent_continues_after_its_last_record(self, hourly, agent_root):
        write_positions(agent_root / "bot", [{"date": "2025-10-01 12:00:00", "id": 3, "positions": {"CASH": 1.0}}])
        assert hourly.get_trading_dates("2025-10-01 10:00:00", "2025-10-02 11:00:00") == ["2025-10-02 10:00:00", "2025-10-02 11:00:00"]

    def test_a_later_start_than_the_last_record_includes_the_start_itself(self, hourly, agent_root):
        write_positions(agent_root / "bot", [{"date": "2025-10-01 10:00:00", "id": 0, "positions": {"CASH": 1.0}}])
        assert hourly.get_trading_dates("2025-10-02 10:00:00", "2025-10-02 11:00:00") == ["2025-10-02 10:00:00", "2025-10-02 11:00:00"]

    def test_no_price_data_means_nothing_to_trade_and_no_registration(self, project, agent_root):
        agent = make(cls=BaseAgent_Hour, log_path=str(agent_root))
        assert agent.get_trading_dates("2025-10-01 10:00:00", "2025-10-02 11:00:00") == []
        assert not (agent_root / "bot").exists()

    def test_daily_keys_in_the_data_are_ignored(self, project, agent_root):
        # "2025-10-02" would read as midnight, inside the range: it is a daily bar, not an hour to trade
        write_prices(project, {"AAPL": {"2025-10-02": bar(1), "2025-10-02 10:00:00": bar(1)}})
        agent = make(cls=BaseAgent_Hour, log_path=str(agent_root))
        assert agent.get_trading_dates("2025-10-01 09:00:00", "2025-10-03 09:00:00") == ["2025-10-02 10:00:00"]

    def test_dates_without_a_time_are_refused(self, hourly):
        with pytest.raises(ValueError, match="Only support hour-level trading"):
            hourly.get_trading_dates("2025-10-01", "2025-10-02")

    def test_mixed_formats_are_refused(self, hourly):
        with pytest.raises(ValueError, match="same time format"):
            hourly.get_trading_dates("2025-10-01 10:00:00", "2025-10-02")


class FakeAgentExecutor:
    """Stands in for the langchain agent: replays a script of replies and records what it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def ainvoke(self, payload, config):
        self.calls.append((payload, config))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def reply(text, tool_results=()):
    messages = [SimpleNamespace(content=text, response_metadata={"finish_reason": "stop"}, additional_kwargs={}, name=None, tool_call_id=None)]
    messages += [SimpleNamespace(content=c, tool_call_id="t", name="buy", response_metadata={}, additional_kwargs={}) for c in tool_results]
    return {"messages": messages}


@pytest.fixture()
def session(project, agent_root, monkeypatch, settings):
    write_prices(project, {"AAPL": {"2025-10-01": bar(99, 100), "2025-10-02": bar(100, 105)}, "MSFT": {"2025-10-01": bar(199, 200), "2025-10-02": bar(200, 205)}})
    write_positions(agent_root / "bot", [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 1000.0, "AAPL": 0, "MSFT": 0}}])
    settings(today="2025-10-02")
    holder = {}

    def fake_create_agent(model, tools, system_prompt):
        holder["system_prompt"], holder["tools"] = system_prompt, tools
        return holder["executor"]

    monkeypatch.setattr(base_module, "create_agent", fake_create_agent)
    agent = make(log_path=str(agent_root), max_steps=4)
    agent.model, agent.tools = object(), ["tool"]
    return agent, holder


def log_lines(agent_root, date="2025-10-02"):
    path = agent_root / "bot" / "log" / date / "log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


class TestTradingSession:
    @pytest.mark.parametrize("cls", [BaseAgent, BaseAgent_Hour])
    def test_a_session_that_stops_at_once(self, session, agent_root, cls):
        agent, holder = session
        agent.__class__ = cls  # both classes run the same session
        holder["executor"] = FakeAgentExecutor([reply(f"nothing to do {STOP_SIGNAL}")])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        assert len(holder["executor"].calls) == 1
        assert holder["executor"].calls[0][0]["messages"] == [{"role": "user", "content": "Please analyze and update today's (2025-10-02) positions."}]
        assert holder["executor"].calls[0][1] == {"recursion_limit": 100}
        assert holder["tools"] == ["tool"] and "2025-10-02" in holder["system_prompt"]
        assert get_config_value("LOG_FILE").endswith("log/2025-10-02/log.jsonl")

    def test_it_logs_each_step(self, session, agent_root):
        agent, holder = session
        holder["executor"] = FakeAgentExecutor([reply("thinking", ["result 1", "result 2"]), reply(f"done {STOP_SIGNAL}")])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        lines = log_lines(agent_root)
        assert [entry["signature"] for entry in lines] == ["bot"] * 4
        assert lines[1]["new_messages"] == {"role": "assistant", "content": "thinking"}
        assert lines[2]["new_messages"] == {"role": "user", "content": "Tool results: result 1\nresult 2"}
        assert lines[3]["new_messages"] == [{"role": "assistant", "content": f"done {STOP_SIGNAL}"}]

    def test_the_conversation_grows_between_steps(self, session):
        agent, holder = session
        holder["executor"] = FakeAgentExecutor([reply("step one", ["r1"]), reply(f"{STOP_SIGNAL}")])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        second = holder["executor"].calls[1][0]["messages"]
        assert [m["role"] for m in second] == ["user", "assistant", "user"] and second[1]["content"] == "step one" and second[2]["content"] == "Tool results: r1"

    def test_the_step_limit_ends_the_session(self, session):
        agent, holder = session
        holder["executor"] = FakeAgentExecutor([reply(f"step {i}") for i in range(10)])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        assert len(holder["executor"].calls) == 4  # max_steps

    def test_an_empty_model_turn_is_not_a_stop_signal(self, session):
        agent, holder = session
        holder["executor"] = FakeAgentExecutor([{"messages": []}, reply(STOP_SIGNAL)])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        assert len(holder["executor"].calls) == 2

    def test_tool_messages_without_content_are_skipped_and_other_content_is_stringified(self, session, agent_root):
        agent, holder = session
        holder["executor"] = FakeAgentExecutor([reply("x", [None, 5, ["a"]]), reply(STOP_SIGNAL)])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        assert log_lines(agent_root)[2]["new_messages"]["content"] == "Tool results: 5\n['a']"

    def test_a_failing_agent_call_is_retried_then_raised(self, session):
        agent, holder = session
        holder["executor"] = FakeAgentExecutor([RuntimeError("boom 1"), RuntimeError("boom 2"), RuntimeError("boom 3")])
        with pytest.raises(RuntimeError, match="boom 3"):
            asyncio.run(agent.run_trading_session("2025-10-02"))
        assert len(holder["executor"].calls) == 3  # max_retries

    def test_the_pause_between_model_call_retries_grows(self, session, monkeypatch):
        agent, holder = session
        slept = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        monkeypatch.setattr(base_module.asyncio, "sleep", fake_sleep)
        agent.base_delay = 2
        holder["executor"] = FakeAgentExecutor([RuntimeError("1"), RuntimeError("2"), reply(STOP_SIGNAL)])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        assert slept == [2, 4]

    def test_a_call_that_recovers_on_retry(self, session):
        agent, holder = session
        holder["executor"] = FakeAgentExecutor([RuntimeError("blip"), reply(STOP_SIGNAL)])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        assert len(holder["executor"].calls) == 2

    def test_no_trade_today_records_the_unchanged_position(self, session, agent_root):
        agent, holder = session
        holder["executor"] = FakeAgentExecutor([reply(STOP_SIGNAL)])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        last = read_positions(agent_root / "bot")[-1]
        assert last["this_action"] == {"action": "no_trade", "symbol": "", "amount": 0} and last["date"] == "2025-10-02" and last["positions"]["CASH"] == 1000.0
        assert get_config_value("IF_TRADE") is False

    def test_a_day_with_a_trade_does_not_add_a_no_trade_record(self, session, agent_root):
        agent, holder = session
        write_config_value("IF_TRADE", True)  # what the trade tool sets after a successful order
        holder["executor"] = FakeAgentExecutor([reply(STOP_SIGNAL)])
        asyncio.run(agent.run_trading_session("2025-10-02"))
        assert len(read_positions(agent_root / "bot")) == 1
        assert get_config_value("IF_TRADE") is False  # reset for the next day


class TestRunWithRetryAndRange:
    def test_a_day_that_fails_is_retried_with_a_pause_then_raised(self, session, monkeypatch):
        agent, holder = session
        attempts = []

        async def failing(date):
            attempts.append(date)
            raise RuntimeError("down")

        slept = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        monkeypatch.setattr(agent, "run_trading_session", failing)
        monkeypatch.setattr(base_module.asyncio, "sleep", fake_sleep)
        agent.base_delay = 2
        with pytest.raises(RuntimeError, match="down"):
            asyncio.run(agent.run_with_retry("2025-10-02"))
        assert attempts == ["2025-10-02"] * 3 and slept == [2, 4]

    def test_a_day_that_succeeds_on_the_second_try(self, session, monkeypatch):
        agent, holder = session
        outcomes = [RuntimeError("blip"), None]

        async def flaky(date):
            result = outcomes.pop(0)
            if result:
                raise result

        monkeypatch.setattr(agent, "run_trading_session", flaky)
        asyncio.run(agent.run_with_retry("2025-10-02"))
        assert not outcomes

    @pytest.mark.parametrize("cls", [BaseAgent, BaseAgent_Hour])
    def test_the_range_sets_the_settings_for_each_day_and_runs_it(self, session, monkeypatch, cls):
        agent, holder = session
        agent.__class__ = cls
        monkeypatch.delenv("SIGNATURE")  # the value must come from the settings file the tools read, not from this process's environment
        write_config_value("SIGNATURE", "someone-else")  # ... and the range must overwrite what an earlier run left there
        ran = []

        async def record(date):
            ran.append((date, get_config_value("TODAY_DATE"), get_config_value("SIGNATURE")))

        monkeypatch.setattr(agent, "run_with_retry", record)
        monkeypatch.setattr(agent, "get_trading_dates", lambda a, b: ["2025-10-02", "2025-10-03"])
        asyncio.run(agent.run_date_range("2025-10-01", "2025-10-03"))
        assert ran == [("2025-10-02", "2025-10-02", "bot"), ("2025-10-03", "2025-10-03", "bot")]

    def test_the_range_stops_at_the_first_failed_day(self, session, monkeypatch):
        agent, holder = session
        ran = []

        async def record(date):
            ran.append(date)
            raise RuntimeError("no")

        monkeypatch.setattr(agent, "run_with_retry", record)
        monkeypatch.setattr(agent, "get_trading_dates", lambda a, b: ["2025-10-02", "2025-10-03"])
        with pytest.raises(RuntimeError):
            asyncio.run(agent.run_date_range("2025-10-01", "2025-10-03"))
        assert ran == ["2025-10-02"]

    def test_an_empty_range_does_nothing(self, session, monkeypatch, capsys):
        agent, holder = session
        monkeypatch.setattr(agent, "get_trading_dates", lambda a, b: [])
        asyncio.run(agent.run_date_range("2025-10-01", "2025-10-01"))
        assert "No trading days to process" in capsys.readouterr().out

    def test_the_hourly_class_uses_the_inherited_loop(self):
        assert BaseAgent_Hour.run_date_range is BaseAgent.run_date_range
        assert BaseAgent_Hour.run_trading_session is BaseAgent.run_trading_session


class TestPositionSummary:
    def test_the_latest_record(self, agent_root):
        write_positions(agent_root / "bot", [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 5.0}}, {"date": "2025-10-02", "id": 1, "positions": {"CASH": 4.0}}])
        assert make(log_path=str(agent_root)).get_position_summary() == {"signature": "bot", "latest_date": "2025-10-02", "positions": {"CASH": 4.0}, "total_records": 2}

    def test_no_file(self, agent_root):
        assert make(log_path=str(agent_root)).get_position_summary() == {"error": "Position file does not exist"}

    def test_an_empty_file_and_blank_lines(self, agent_root):
        path = agent_root / "bot" / "position" / "position.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("\n\n")
        assert make(log_path=str(agent_root)).get_position_summary() == {"error": "No position records"}
