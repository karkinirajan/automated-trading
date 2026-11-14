import pytest
import requests

from agent_tools import tool_jina_search as jina
from tools.general_tools import write_config_value


class FakeResponse:
    def __init__(self, payload=None, status=200, raises=None):
        self.payload, self.status_code, self.raises = payload, status, raises

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if self.raises:
            raise self.raises
        return self.payload


@pytest.fixture()
def http(monkeypatch):
    calls: list[dict] = []
    responses: list = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        answer = responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(jina.requests, "get", fake_get)
    monkeypatch.setenv("JINA_API_KEY", "secret-key")
    return calls, responses


def search_result(*items):
    return FakeResponse({"data": list(items)})


PAGE = {"data": {"url": "https://x.example/p", "title": "T", "description": "D", "content": "C" * 2000, "publishedTime": "2025-10-01"}}


class TestSearchRequest:
    def test_the_query_is_encoded_as_a_parameter_not_pasted_into_the_url(self, http):
        calls, responses = http
        responses.append(search_result())
        jina.WebScrapingJinaTool()._jina_search("nvidia earnings&n=100#frag")
        call = calls[0]
        assert call["url"] == "https://s.jina.ai/"
        assert call["params"] == {"q": "nvidia earnings&n=100#frag", "n": 1}

    def test_the_request_has_a_timeout_and_a_bearer_key(self, http):
        calls, responses = http
        responses.append(search_result())
        jina.WebScrapingJinaTool()._jina_search("q")
        assert calls[0]["timeout"] == (5, 30)
        assert calls[0]["headers"]["Authorization"] == "Bearer secret-key"
        assert calls[0]["headers"]["X-Respond-With"] == "no-content"
        assert calls[0]["headers"]["Accept"] == "application/json"

    def test_the_key_is_required(self, monkeypatch):
        monkeypatch.delenv("JINA_API_KEY", raising=False)
        with pytest.raises(ValueError, match="JINA_API_KEY"):
            jina.WebScrapingJinaTool()


class TestSearchFiltering:
    def test_future_and_undated_results_are_dropped(self, http):
        calls, responses = http
        write_config_value("TODAY_DATE", "2025-10-15")
        responses.append(
            search_result(
                {"url": "https://future.example", "date": "2025-10-20"},
                {"url": "https://undated.example"},
                {"url": "https://old.example", "date": "2025-10-01"},
            )
        )
        assert jina.WebScrapingJinaTool()._jina_search("q") == ["https://old.example"]

    def test_without_a_simulated_date_results_are_kept(self, http):
        calls, responses = http
        responses.append(search_result({"url": "https://a.example", "date": "2099-01-01"}))
        assert jina.WebScrapingJinaTool()._jina_search("q") == ["https://a.example"]

    @pytest.mark.parametrize("payload", [None, [], "text", {"no": "data"}, {"data": None}, {"data": "x"}, {"data": {"url": "u"}}])
    def test_an_unexpected_response_shape_is_an_empty_result(self, http, payload):
        calls, responses = http
        responses.append(FakeResponse(payload))
        assert jina.WebScrapingJinaTool()._jina_search("q") == []

    def test_a_failed_request_is_an_empty_result(self, http):
        calls, responses = http
        responses.append(requests.ConnectionError("down"))
        assert jina.WebScrapingJinaTool()._jina_search("q") == []

    def test_an_error_status_is_an_empty_result(self, http):
        calls, responses = http
        responses.append(FakeResponse({"data": [{"url": "https://a.example", "date": "2025-01-01"}]}, status=429))
        assert jina.WebScrapingJinaTool()._jina_search("q") == []

    def test_a_response_that_is_not_json_is_an_empty_result(self, http):
        calls, responses = http
        responses.append(FakeResponse(raises=ValueError("no json")))
        assert jina.WebScrapingJinaTool()._jina_search("q") == []


class TestScrape:
    def test_a_page(self, http):
        calls, responses = http
        responses.append(FakeResponse(PAGE))
        out = jina.WebScrapingJinaTool()._jina_scrape("https://x.example/p")
        assert out["url"] == "https://x.example/p" and out["title"] == "T" and out["publish_time"] == "2025-10-01"
        assert calls[0]["url"] == "https://r.jina.ai/https://x.example/p"
        assert calls[0]["timeout"] == (5, 30) and calls[0]["headers"]["Authorization"] == "Bearer secret-key"

    def test_a_page_without_a_publish_time(self, http):
        calls, responses = http
        page = {"data": {k: v for k, v in PAGE["data"].items() if k != "publishedTime"}}
        responses.append(FakeResponse(page))
        assert jina.WebScrapingJinaTool()._jina_scrape("u")["publish_time"] == "unknown"

    @pytest.mark.parametrize("answer", [FakeResponse(status=500), FakeResponse({"data": {}}), FakeResponse({}), requests.Timeout("slow")])
    def test_a_failure_is_an_error_entry_not_an_exception(self, http, answer):
        calls, responses = http
        responses.append(answer)
        out = jina.WebScrapingJinaTool()._jina_scrape("https://x.example")
        assert out["url"] == "https://x.example" and out["content"] == "" and out["error"]


class TestTool:
    def test_it_reads_at_most_one_page(self, http):
        calls, responses = http
        responses.extend([search_result({"url": "https://a.example", "date": "2025-01-01"}, {"url": "https://b.example", "date": "2025-01-02"}), FakeResponse(PAGE)])
        write_config_value("TODAY_DATE", "2025-10-15")
        results = jina.WebScrapingJinaTool()("q")
        assert len(results) == 1 and len(calls) == 2

    def test_get_information_formats_the_page_and_cuts_the_content(self, http):
        calls, responses = http
        responses.extend([search_result({"url": "https://x.example/p", "date": "2025-01-01"}), FakeResponse(PAGE)])
        write_config_value("TODAY_DATE", "2025-10-15")
        text = jina.get_information.fn("q") if hasattr(jina.get_information, "fn") else jina.get_information("q")
        assert "URL: https://x.example/p" in text and "Title: T" in text and "Description: D" in text and "Publish Time: 2025-10-01" in text
        assert "C" * 1000 + "..." in text and "C" * 1001 not in text

    def test_get_information_with_nothing_found(self, http):
        calls, responses = http
        responses.append(search_result())
        fn = jina.get_information.fn if hasattr(jina.get_information, "fn") else jina.get_information
        assert "found no results" in fn("nothing")

    def test_get_information_reports_a_scrape_error(self, http):
        calls, responses = http
        responses.extend([search_result({"url": "https://x.example", "date": "2025-01-01"}), FakeResponse(status=500)])
        write_config_value("TODAY_DATE", "2025-10-15")
        fn = jina.get_information.fn if hasattr(jina.get_information, "fn") else jina.get_information
        assert fn("q").startswith("Error: ")

    def test_get_information_without_a_key(self, monkeypatch):
        monkeypatch.delenv("JINA_API_KEY", raising=False)
        fn = jina.get_information.fn if hasattr(jina.get_information, "fn") else jina.get_information
        assert "Search tool execution failed" in fn("q")

    def test_the_server_starts_on_the_search_port(self, monkeypatch):
        started = {}
        monkeypatch.setattr(jina.mcp, "run", lambda **kw: started.update(kw))
        monkeypatch.setenv("SEARCH_HTTP_PORT", "9101")
        jina.run_server(jina.mcp, "SEARCH_HTTP_PORT", 8001)
        assert started == {"transport": "streamable-http", "host": "127.0.0.1", "port": 9101}
