import json

import pytest

from tools import agent_context
from tools.agent_context import AGENT_HEADER, TOKEN_HEADER, calling_agent, runtime_env_path_override
from tools.general_tools import get_config_value, write_config_value


@pytest.fixture()
def headers(monkeypatch):
    """Pretend the tool call arrived with these HTTP headers."""
    current: dict[str, str] = {}
    monkeypatch.setattr("fastmcp.server.dependencies.get_http_headers", lambda *a, **k: dict(current))
    return current


class TestCallingAgent:
    def test_without_a_header_nothing_changes(self, headers):
        with calling_agent() as caller:
            assert caller is None and runtime_env_path_override() is None
        write_config_value("A", 1)
        assert get_config_value("A") == 1

    def test_the_header_selects_that_agents_settings_file(self, headers, project):
        headers[AGENT_HEADER] = "alice"
        with calling_agent() as caller:
            assert caller == "alice"
            assert runtime_env_path_override() == str(project / "agent_data" / "alice" / ".runtime_env.json")

    def test_settings_are_read_from_that_agents_file_not_the_servers_own(self, headers, project):
        (project / "agent_data" / "alice").mkdir()
        (project / "agent_data" / "alice" / ".runtime_env.json").write_text(json.dumps({"TODAY_DATE": "2025-10-02"}))
        write_config_value("TODAY_DATE", "1999-01-01")  # the server's own file (RUNTIME_ENV_PATH)
        headers[AGENT_HEADER] = "alice"
        with calling_agent():
            assert get_config_value("TODAY_DATE") == "2025-10-02"
        assert get_config_value("TODAY_DATE") == "1999-01-01"

    def test_writes_go_to_that_agents_file(self, headers, project):
        (project / "agent_data" / "alice").mkdir()
        headers[AGENT_HEADER] = "alice"
        with calling_agent():
            write_config_value("IF_TRADE", True)
        assert json.loads((project / "agent_data" / "alice" / ".runtime_env.json").read_text()) == {"IF_TRADE": True}
        assert get_config_value("IF_TRADE") is None  # the server's own file is untouched

    def test_an_agent_with_no_folder_gets_no_folder_created_by_a_read(self, headers, project):
        headers[AGENT_HEADER] = "ghost"
        with calling_agent():
            assert get_config_value("TODAY_DATE") is None
        assert not (project / "agent_data" / "ghost").exists()

    @pytest.mark.parametrize("value", ["../escape", "a/b", "..", ".hidden", "x" * 101, "a..b"])
    def test_a_signature_that_is_not_a_plain_folder_name_is_refused(self, headers, value):
        headers[AGENT_HEADER] = value
        with pytest.raises(ValueError, match="unsafe agent signature"), calling_agent():
            pass
        assert runtime_env_path_override() is None

    def test_the_context_ends_with_the_call_even_when_it_fails(self, headers):
        headers[AGENT_HEADER] = "alice"
        with pytest.raises(RuntimeError), calling_agent():
            raise RuntimeError("tool failed")
        assert runtime_env_path_override() is None

    def test_nested_and_consecutive_calls_do_not_leak_into_each_other(self, headers):
        headers[AGENT_HEADER] = "alice"
        with calling_agent():
            headers[AGENT_HEADER] = "bob"
            with calling_agent() as inner:
                assert inner == "bob"
            assert runtime_env_path_override().endswith("alice/.runtime_env.json")
        assert runtime_env_path_override() is None

    def test_an_empty_header_is_no_header(self, headers):
        headers[AGENT_HEADER] = ""
        with calling_agent() as caller:
            assert caller is None

    def test_outside_an_http_request_there_are_no_headers(self):
        with calling_agent() as caller:  # no monkeypatch: the real get_http_headers() returns {} here
            assert caller is None

    def test_the_header_name_is_lowercase_as_fastmcp_reports_it(self):
        assert AGENT_HEADER == AGENT_HEADER.lower()
        assert agent_context.RUNTIME_ENV_NAME == ".runtime_env.json"


class TestSharedSecret:
    def test_without_a_configured_token_none_is_asked_for(self, headers):
        with calling_agent() as caller:
            assert caller is None

    def test_with_a_token_the_right_one_is_accepted(self, headers, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "s3cret")
        headers.update({TOKEN_HEADER: "s3cret", AGENT_HEADER: "alice"})
        with calling_agent() as caller:
            assert caller == "alice"

    @pytest.mark.parametrize("sent", [None, "", "wrong", "s3cret ", "S3CRET", "s3cre"])
    def test_a_missing_or_wrong_token_is_refused(self, headers, monkeypatch, sent):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "s3cret")
        headers[AGENT_HEADER] = "alice"
        if sent is not None:
            headers[TOKEN_HEADER] = sent
        with pytest.raises(PermissionError, match="requires the MCP token"), calling_agent():
            pass
        assert runtime_env_path_override() is None

    def test_the_token_is_required_even_when_no_agent_is_named(self, headers, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "s3cret")
        with pytest.raises(PermissionError), calling_agent():
            pass

    def test_an_empty_configured_token_means_none_is_required(self, headers, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "")
        with calling_agent():
            pass

    def test_a_non_ascii_token_is_compared_without_error(self, headers, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "sécret-日本")
        headers[TOKEN_HEADER] = "sécret-日本"
        with calling_agent():
            pass

    def test_the_error_does_not_reveal_the_token(self, headers, monkeypatch):
        monkeypatch.setenv("MCP_AUTH_TOKEN", "s3cret-value")
        with pytest.raises(PermissionError) as exc, calling_agent():
            pass
        assert "s3cret-value" not in str(exc.value)
