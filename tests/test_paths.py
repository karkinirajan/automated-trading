import pytest

from tools import paths
from tools.paths import agent_dir, merged_prices_file, position_file, safe_signature


@pytest.mark.parametrize(
    "name",
    ["gpt-5", "claude-3.7-sonnet", "qwen3-max", "MiniMax-M2", "deepseek-chat-v3.1", "gemini-2.5-flash", "a", "A_b-c.d", "x" * 100],
)
def test_the_models_in_the_default_config_are_accepted(name):
    assert safe_signature(name) == name


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../x", "a/b", "a\\b", "/etc", ".hidden", "-x", "_x", "a..b", "a b", "a\x00b", "x" * 101, "é", "a/../b", "a\n"],
)
def test_anything_that_could_leave_the_agent_folder_is_refused(name):
    with pytest.raises(ValueError, match="unsafe agent signature"):
        safe_signature(name)


@pytest.mark.parametrize("value", [None, 5, b"abc", ["a"], {"a": 1}])
def test_a_signature_must_be_text(value):
    with pytest.raises(ValueError):
        safe_signature(value)


def test_the_message_does_not_echo_a_long_name():
    with pytest.raises(ValueError) as exc:
        safe_signature("/" + "x" * 500)
    assert len(str(exc.value)) < 100


def test_the_paths_are_under_the_data_folder(project):
    assert agent_dir("bot") == project / "agent_data" / "bot"
    assert position_file("bot") == project / "agent_data" / "bot" / "position" / "position.jsonl"
    assert merged_prices_file() == project / "merged.jsonl"


def test_an_unsafe_signature_never_becomes_a_path():
    with pytest.raises(ValueError):
        agent_dir("../escape")
    with pytest.raises(ValueError):
        position_file("../escape")


def test_the_unpatched_defaults(monkeypatch):
    monkeypatch.undo()
    assert paths.DATA_DIR == paths.PROJECT_ROOT / "data"
    assert paths.AGENT_DATA_DIR == paths.PROJECT_ROOT / "data" / "agent_data"
