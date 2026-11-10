from pathlib import Path

import pytest

from tools import paths


@pytest.fixture(autouse=True)
def project(monkeypatch, tmp_path) -> Path:
    """Every test runs against its own data folder, never the repository's, with a clean environment."""
    data_dir = tmp_path / "data"
    (data_dir / "agent_data").mkdir(parents=True)
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    monkeypatch.setattr(paths, "AGENT_DATA_DIR", data_dir / "agent_data")
    for name in ("SIGNATURE", "TODAY_DATE", "IF_TRADE", "RUNTIME_ENV_PATH", "MCP_HOST", "INIT_DATE", "END_DATE", "JINA_API_KEY", "ALPHAADVANTAGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RUNTIME_ENV_PATH", str(tmp_path / "runtime_env.json"))
    monkeypatch.chdir(tmp_path)
    return data_dir


@pytest.fixture()
def agent(project) -> Path:
    """The data folder of an agent called "bot"."""
    folder = project / "agent_data" / "bot"
    folder.mkdir(parents=True)
    return folder


@pytest.fixture()
def settings(monkeypatch):
    """Set the runtime settings the tools read: today's date and the agent's signature."""

    def _set(today: str | None = "2025-10-02", signature: str | None = "bot") -> None:
        from tools.general_tools import write_config_value

        if today is not None:
            write_config_value("TODAY_DATE", today)
        if signature is not None:
            monkeypatch.setenv("SIGNATURE", signature)
            write_config_value("SIGNATURE", signature)

    return _set


def pytest_sessionfinish(session, exitstatus):
    # a test must never have written into the repository's own agent data
    leaked = [p for p in Path(__file__).resolve().parents[1].glob("data/agent_data/bot*")]
    assert not leaked, f"a test wrote into the repository: {leaked}"

