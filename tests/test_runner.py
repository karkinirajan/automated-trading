import asyncio
import json
import os

import pytest

import main as main_module
import main_parrallel
from agent import runner
from agent.runner import (
    AGENT_REGISTRY,
    ConfigError,
    enabled_models,
    get_agent_class,
    load_config,
    prepare_runtime_env,
    run_dates,
    run_model,
)
from tools.general_tools import get_config_value


class TestAgentClass:
    def test_the_registered_classes_load(self):
        for agent_type in AGENT_REGISTRY:
            assert get_agent_class(agent_type).__name__ == AGENT_REGISTRY[agent_type]["class"]

    def test_an_unknown_type(self):
        with pytest.raises(ValueError, match="(?s)Unsupported agent type: Nope.*BaseAgent, BaseAgent_Hour"):
            get_agent_class("Nope")

    def test_a_module_that_cannot_be_imported(self, monkeypatch):
        monkeypatch.setitem(AGENT_REGISTRY, "Broken", {"module": "agent.does_not_exist", "class": "X"})
        with pytest.raises(ImportError, match="Unable to import agent module agent.does_not_exist") as exc:
            get_agent_class("Broken")
        assert exc.value.__cause__ is not None

    def test_a_class_the_module_does_not_have(self, monkeypatch):
        monkeypatch.setitem(AGENT_REGISTRY, "Broken", {"module": "agent.runner", "class": "NoSuchClass"})
        with pytest.raises(AttributeError, match="Class NoSuchClass not found"):
            get_agent_class("Broken")


class TestLoadConfig:
    def test_a_file(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"agent_type": "BaseAgent"}))
        assert load_config(path) == {"agent_type": "BaseAgent"}
        assert load_config(str(path)) == {"agent_type": "BaseAgent"}

    def test_the_default_config_is_valid_and_lists_the_models(self):
        config = load_config()
        assert config["agent_type"] in AGENT_REGISTRY
        assert {m["signature"] for m in config["models"]} >= {"gpt-5", "claude-3.7-sonnet"}
        assert run_dates(config)  # and its dates are valid

    def test_a_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="does not exist"):
            load_config(tmp_path / "nope.json")

    def test_bad_json(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text("{oops")
        with pytest.raises(ConfigError, match="JSON format error") as exc:
            load_config(path)
        assert exc.value.__cause__ is not None

    def test_not_an_object(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text("[1]")
        with pytest.raises(ConfigError, match="must contain a JSON object"):
            load_config(path)

    def test_an_unreadable_file(self, tmp_path):
        with pytest.raises(ConfigError, match="Failed to load"):
            load_config(tmp_path)  # a directory


class TestRunDates:
    CONFIG = {"date_range": {"init_date": "2025-10-01", "end_date": "2025-10-21"}}

    def test_from_the_config(self):
        assert run_dates(self.CONFIG, {}) == ("2025-10-01", "2025-10-21")

    def test_the_environment_overrides_each_end(self):
        assert run_dates(self.CONFIG, {"INIT_DATE": "2025-10-05"}) == ("2025-10-05", "2025-10-21")
        assert run_dates(self.CONFIG, {"END_DATE": "2025-10-10"}) == ("2025-10-01", "2025-10-10")

    def test_it_reads_the_process_environment_by_default(self, monkeypatch):
        monkeypatch.setenv("END_DATE", "2025-10-09")
        assert run_dates(self.CONFIG) == ("2025-10-01", "2025-10-09")

    def test_times_are_accepted(self):
        assert run_dates({"date_range": {"init_date": "2025-10-01 09:00:00", "end_date": "2025-10-01 15:00:00"}}, {}) == ("2025-10-01 09:00:00", "2025-10-01 15:00:00")

    def test_the_same_day_is_allowed(self):
        assert run_dates({"date_range": {"init_date": "2025-10-01", "end_date": "2025-10-01"}}, {})

    def test_a_start_after_the_end(self):
        with pytest.raises(ConfigError, match="INIT_DATE is greater than END_DATE"):
            run_dates(self.CONFIG, {"INIT_DATE": "2025-11-01"})

    @pytest.mark.parametrize("config", [{}, {"date_range": {}}, {"date_range": {"init_date": "2025-10-01"}}, {"date_range": None}])
    def test_missing_dates(self, config):
        with pytest.raises(ConfigError, match="needs date_range"):
            run_dates(config, {})

    @pytest.mark.parametrize("bad", ["10/01/2025", "yesterday", "2025-13-01", "2025-10-01T10:00:00"])
    def test_malformed_dates(self, bad):
        with pytest.raises(ConfigError, match="Dates must be"):
            run_dates(self.CONFIG, {"INIT_DATE": bad})

    def test_a_date_that_is_not_text(self):
        with pytest.raises(ConfigError, match="Dates must be"):
            run_dates({"date_range": {"init_date": 20251001, "end_date": "2025-10-21"}}, {})


class TestEnabledModels:
    CONFIG = {"models": [{"signature": "a"}, {"signature": "b", "enabled": False}, {"signature": "c", "enabled": True}]}

    def test_disabled_models_are_left_out(self):
        assert [m["signature"] for m in enabled_models(self.CONFIG)] == ["a", "c"]

    def test_one_signature(self):
        assert [m["signature"] for m in enabled_models(self.CONFIG, "c")] == ["c"]
        assert enabled_models(self.CONFIG, "b") == []  # still disabled

    def test_no_models(self):
        assert enabled_models({}) == []


class TestRuntimeEnv:
    def test_it_points_the_process_at_the_agent_and_resets_the_state(self, project):
        path = prepare_runtime_env("bot", "2025-10-21")
        assert path == project / "agent_data" / "bot" / ".runtime_env.json"
        assert os.environ["RUNTIME_ENV_PATH"] == str(path) and os.environ["SIGNATURE"] == "bot"
        assert get_config_value("TODAY_DATE") == "2025-10-21"
        assert get_config_value("IF_TRADE") is False

    def test_an_unsafe_signature_is_refused(self):
        with pytest.raises(ValueError):
            prepare_runtime_env("../x", "2025-10-21")


class FakeAgent:
    instances: list = []
    fail = False

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeAgent.instances.append(self)

    def __str__(self):
        return "FakeAgent"

    async def initialize(self):
        pass

    async def run_date_range(self, init, end):
        if FakeAgent.fail:
            raise RuntimeError("model failed")
        self.range = (init, end)

    def get_position_summary(self):
        return {"latest_date": "2025-10-21", "total_records": 3, "positions": {"CASH": 1234.5}}


@pytest.fixture()
def fake_agent():
    FakeAgent.instances = []
    FakeAgent.fail = False
    return FakeAgent


class TestRunModel:
    MODEL = {"name": "GPT", "basemodel": "openai/gpt-5", "signature": "gpt-5", "openai_base_url": "http://x", "openai_api_key": "k"}

    def test_a_model_runs_over_the_range_with_its_settings(self, fake_agent, capsys):
        done = asyncio.run(run_model(fake_agent, self.MODEL, "2025-10-01", "2025-10-21", {"max_steps": 7, "initial_cash": 500.0}, {"log_path": "/tmp/l"}))
        assert done is True
        agent = fake_agent.instances[0]
        assert agent.range == ("2025-10-01", "2025-10-21")
        assert agent.kwargs["signature"] == "gpt-5" and agent.kwargs["basemodel"] == "openai/gpt-5"
        assert agent.kwargs["max_steps"] == 7 and agent.kwargs["initial_cash"] == 500.0 and agent.kwargs["init_date"] == "2025-10-01"
        assert agent.kwargs["max_retries"] == 3 and agent.kwargs["base_delay"] == 0.5 and agent.kwargs["log_path"] == "/tmp/l"
        assert agent.kwargs["openai_base_url"] == "http://x" and agent.kwargs["openai_api_key"] == "k"
        assert len(agent.kwargs["stock_symbols"]) == 101 or len(agent.kwargs["stock_symbols"]) > 90
        assert "Cash balance: $1234.50" in capsys.readouterr().out

    def test_the_defaults(self, fake_agent):
        asyncio.run(run_model(fake_agent, self.MODEL, "a", "b", {}, {}))
        kwargs = fake_agent.instances[0].kwargs
        assert (kwargs["max_steps"], kwargs["max_retries"], kwargs["base_delay"], kwargs["initial_cash"], kwargs["log_path"]) == (10, 3, 0.5, 10000.0, "./data/agent_data")

    @pytest.mark.parametrize("model", [{"name": "x", "signature": "s"}, {"name": "x", "basemodel": "b"}, {"basemodel": "", "signature": "s"}])
    def test_an_incomplete_entry_is_skipped_and_reported(self, fake_agent, model):
        assert asyncio.run(run_model(fake_agent, model, "a", "b", {}, {})) is False
        assert not fake_agent.instances

    def test_a_failing_model_raises(self, fake_agent):
        fake_agent.fail = True
        with pytest.raises(RuntimeError, match="model failed"):
            asyncio.run(run_model(fake_agent, self.MODEL, "a", "b", {}, {}))


class TestEntryPoints:
    @pytest.fixture()
    def config_file(self, tmp_path):
        def make(models, **extra):
            path = tmp_path / "c.json"
            path.write_text(json.dumps({"agent_type": "BaseAgent", "date_range": {"init_date": "2025-10-01", "end_date": "2025-10-02"}, "models": models, **extra}))
            return path

        return make

    @pytest.fixture(autouse=True)
    def use_fake_agent(self, monkeypatch, fake_agent):
        monkeypatch.setattr(main_module, "get_agent_class", lambda t: fake_agent)
        monkeypatch.setattr(main_parrallel, "get_agent_class", lambda t: fake_agent)

    @pytest.mark.parametrize("entry", [main_module, main_parrallel])
    def test_a_good_run_exits_0(self, entry, config_file, fake_agent):
        path = config_file([{"name": "A", "basemodel": "m", "signature": "a"}])
        assert asyncio.run(entry.main(str(path))) == 0
        assert len(fake_agent.instances) == 1

    @pytest.mark.parametrize("entry", [main_module, main_parrallel])
    def test_a_failed_model_exits_1(self, entry, config_file, fake_agent):
        fake_agent.fail = True
        path = config_file([{"name": "A", "basemodel": "m", "signature": "a"}])
        assert asyncio.run(entry.main(str(path))) == 1

    @pytest.mark.parametrize("entry", [main_module, main_parrallel])
    def test_a_missing_config_exits_1(self, entry, tmp_path):
        assert asyncio.run(entry.main(str(tmp_path / "nope.json"))) == 1

    @pytest.mark.parametrize("entry", [main_module, main_parrallel])
    def test_bad_dates_exit_1(self, entry, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"date_range": {"init_date": "2025-10-05", "end_date": "2025-10-01"}, "models": []}))
        assert asyncio.run(entry.main(str(path))) == 1

    @pytest.mark.parametrize("entry", [main_module, main_parrallel])
    def test_an_unknown_agent_type_exits_1(self, entry, config_file, monkeypatch):
        monkeypatch.setattr(entry, "get_agent_class", runner.get_agent_class)
        path = config_file([], agent_type="Nope")
        assert asyncio.run(entry.main(str(path))) == 1

    def test_the_sequential_runner_stops_at_the_first_failed_model(self, config_file, fake_agent):
        fake_agent.fail = True
        path = config_file([{"name": "A", "basemodel": "m", "signature": "a"}, {"name": "B", "basemodel": "m", "signature": "b"}])
        assert asyncio.run(main_module.main(str(path))) == 1
        assert len(fake_agent.instances) == 1

    def test_the_sequential_runner_runs_every_enabled_model(self, config_file, fake_agent):
        path = config_file([{"name": "A", "basemodel": "m", "signature": "a"}, {"name": "B", "basemodel": "m", "signature": "b", "enabled": False}, {"name": "C", "basemodel": "m", "signature": "c"}])
        assert asyncio.run(main_module.main(str(path))) == 0
        assert [i.kwargs["signature"] for i in fake_agent.instances] == ["a", "c"]

    def test_the_parallel_runner_runs_one_signature_in_process(self, config_file, fake_agent):
        path = config_file([{"name": "A", "basemodel": "m", "signature": "a"}, {"name": "B", "basemodel": "m", "signature": "b"}])
        assert asyncio.run(main_parrallel.main(str(path), "b")) == 0
        assert [i.kwargs["signature"] for i in fake_agent.instances] == ["b"]

    def test_the_parallel_runner_with_no_enabled_model_is_fine(self, config_file):
        assert asyncio.run(main_parrallel.main(str(config_file([])))) == 0


class FakeProcess:
    def __init__(self, code):
        self.code = code

    async def wait(self):
        return self.code


class TestParallelSubprocesses:
    def spawn(self, monkeypatch, codes):
        started = []

        async def fake_exec(*cmd):
            started.append(cmd)
            return FakeProcess(codes[len(started) - 1])

        monkeypatch.setattr(main_parrallel.asyncio, "create_subprocess_exec", fake_exec)
        return started

    MODELS = [{"signature": "a"}, {"signature": "b"}, {"name": "no signature"}]

    def test_each_model_gets_its_own_process(self, monkeypatch):
        started = self.spawn(monkeypatch, [0, 0])
        assert asyncio.run(main_parrallel._spawn_model_subprocesses("conf.json", self.MODELS)) == 0
        assert len(started) == 2
        assert started[0][-3:] == ("conf.json", "--signature", "a") and started[1][-2:] == ("--signature", "b")

    def test_without_a_config_path_none_is_passed(self, monkeypatch):
        started = self.spawn(monkeypatch, [0])
        asyncio.run(main_parrallel._spawn_model_subprocesses(None, [{"signature": "a"}]))
        assert started[0][-2:] == ("--signature", "a") and "None" not in started[0]

    def test_one_failed_process_fails_the_run(self, monkeypatch):
        self.spawn(monkeypatch, [0, 3])
        assert asyncio.run(main_parrallel._spawn_model_subprocesses(None, self.MODELS)) == 1

    def test_multiple_models_go_through_subprocesses_and_the_code_is_returned(self, monkeypatch, tmp_path, fake_agent):
        self.spawn(monkeypatch, [0, 1])
        monkeypatch.setattr(main_parrallel, "get_agent_class", lambda t: fake_agent)
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"date_range": {"init_date": "2025-10-01", "end_date": "2025-10-02"}, "models": [{"signature": "a", "basemodel": "m"}, {"signature": "b", "basemodel": "m"}]}))
        assert asyncio.run(main_parrallel.main(str(path))) == 1
        assert not fake_agent.instances  # they ran in the subprocesses, not here
