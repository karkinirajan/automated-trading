import os
from types import SimpleNamespace

import pytest

from tools import general_tools
from tools.general_tools import (
    extract_conversation,
    extract_first_tool_message_content,
    extract_tool_messages,
    get_config_value,
    write_config_value,
)


class TestConfigStore:
    def test_a_written_value_is_read_back(self):
        write_config_value("TODAY_DATE", "2025-10-02")
        assert get_config_value("TODAY_DATE") == "2025-10-02"

    def test_values_of_any_json_type(self):
        write_config_value("IF_TRADE", True)
        write_config_value("N", 3)
        write_config_value("L", [1, "a"])
        assert (get_config_value("IF_TRADE"), get_config_value("N"), get_config_value("L")) == (True, 3, [1, "a"])

    def test_the_file_beats_the_environment_and_the_environment_beats_the_default(self, monkeypatch):
        monkeypatch.setenv("KEY", "from-env")
        assert get_config_value("KEY") == "from-env"
        write_config_value("KEY", "from-file")
        assert get_config_value("KEY") == "from-file"
        assert get_config_value("MISSING", "fallback") == "fallback"
        assert get_config_value("MISSING") is None

    def test_a_write_keeps_the_other_values(self):
        write_config_value("A", 1)
        write_config_value("B", 2)
        assert (get_config_value("A"), get_config_value("B")) == (1, 2)

    def test_the_file_is_replaced_atomically_and_no_temporary_file_is_left(self, tmp_path):
        write_config_value("A", 1)
        assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("runtime_env")) == ["runtime_env.json"]

    def test_a_damaged_file_reads_as_no_settings(self, tmp_path):
        (tmp_path / "runtime_env.json").write_text("{ not json")
        assert get_config_value("A", "d") == "d"
        write_config_value("A", 1)  # and is repaired by the next write
        assert get_config_value("A") == 1

    def test_a_file_that_is_not_an_object_reads_as_no_settings(self, tmp_path):
        (tmp_path / "runtime_env.json").write_text('["A"]')  # a list that "contains" the key must not be read as settings
        assert get_config_value("A", "d") == "d"
        write_config_value("A", 1)  # and it is replaced by the next write
        assert get_config_value("A") == 1

    def test_a_failed_write_is_reported_and_leaves_the_file_alone(self, tmp_path, monkeypatch, capsys):
        write_config_value("A", 1)
        monkeypatch.setattr(general_tools.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
        write_config_value("A", 2)
        assert "Error writing config" in capsys.readouterr().out
        assert get_config_value("A") == 1
        assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]

    def test_a_missing_path_is_reported(self, monkeypatch, capsys):
        monkeypatch.delenv("RUNTIME_ENV_PATH")
        write_config_value("A", 1)
        assert "not persisted" in capsys.readouterr().out
        assert get_config_value("A", "d") == "d"

    def test_the_default_path_comes_from_the_signature_and_is_validated(self, project, monkeypatch):
        monkeypatch.delenv("RUNTIME_ENV_PATH")
        monkeypatch.setenv("SIGNATURE", "bot")
        write_config_value("A", 1)
        assert os.environ["RUNTIME_ENV_PATH"] == str(project / "agent_data" / "bot" / ".runtime_env.json")
        assert get_config_value("A") == 1

    def test_an_unsafe_signature_in_the_environment_is_refused(self, monkeypatch):
        monkeypatch.delenv("RUNTIME_ENV_PATH")
        monkeypatch.setenv("SIGNATURE", "../../etc")
        with pytest.raises(ValueError):
            get_config_value("A")

    def test_a_value_is_unicode_safe(self):
        write_config_value("N", "日本語 🙂")
        assert get_config_value("N") == "日本語 🙂"


def msg(**fields):
    return SimpleNamespace(**fields)


class TestExtractConversation:
    def test_all_returns_the_messages(self):
        messages = [{"content": "a"}]
        assert extract_conversation({"messages": messages}, "all") is messages
        assert extract_conversation({}, "all") == []
        assert extract_conversation({"messages": None}, "all") == []

    def test_final_prefers_the_last_message_that_stopped(self):
        conv = {
            "messages": [
                {"content": "first", "response_metadata": {"finish_reason": "stop"}},
                {"content": "second", "response_metadata": {"finish_reason": "stop"}},
                {"content": "thinking", "response_metadata": {"finish_reason": "tool_calls"}},
            ]
        }
        assert extract_conversation(conv, "final") == "second"

    def test_final_skips_empty_content(self):
        conv = {"messages": [{"content": "answer", "response_metadata": {"finish_reason": "stop"}}, {"content": "  ", "response_metadata": {"finish_reason": "stop"}}]}
        assert extract_conversation(conv, "final") == "answer"

    def test_final_falls_back_to_the_last_plain_assistant_message(self):
        conv = {
            "messages": [
                {"content": "plain"},
                {"content": "calling", "additional_kwargs": {"tool_calls": [1]}},
                {"content": "tool result", "tool_call_id": "t1"},
                {"content": "named tool", "name": "buy"},
            ]
        }
        assert extract_conversation(conv, "final") == "plain"

    def test_final_works_on_objects_too(self):
        conv = SimpleNamespace(messages=[msg(content="hi", response_metadata={"finish_reason": "stop"})])
        assert extract_conversation(conv, "final") == "hi"

    def test_final_with_additional_kwargs_as_an_object(self):
        conv = {"messages": [msg(content="x", additional_kwargs=SimpleNamespace(tool_calls=[1])), msg(content="y", additional_kwargs=SimpleNamespace(tool_calls=None))]}
        assert extract_conversation(conv, "final") == "y"

    def test_final_with_nothing(self):
        assert extract_conversation({"messages": []}, "final") is None
        assert extract_conversation({"messages": [{"content": ["not text"]}]}, "final") is None

    def test_an_unknown_output_type(self):
        with pytest.raises(ValueError, match="'final' or 'all'"):
            extract_conversation({}, "summary")


class TestToolMessages:
    CONV = {
        "messages": [
            {"content": "question"},
            {"content": "calling", "response_metadata": {"finish_reason": "tool_calls"}, "name": "assistant"},
            {"content": "result 1", "tool_call_id": "t1"},
            {"content": "result 2", "name": "buy"},
            {"content": "answer", "response_metadata": {"finish_reason": "stop"}},
        ]
    }

    def test_tool_messages_are_found(self):
        assert [m["content"] for m in extract_tool_messages(self.CONV)] == ["result 1", "result 2"]

    def test_the_first_tool_message_content(self):
        assert extract_first_tool_message_content(self.CONV) == "result 1"

    def test_no_tool_messages(self):
        assert extract_tool_messages({"messages": [{"content": "x"}]}) == []
        assert extract_first_tool_message_content({"messages": []}) is None

    def test_object_messages(self):
        conv = {"messages": [msg(content="r", tool_call_id="t")]}
        assert extract_first_tool_message_content(conv) == "r"
