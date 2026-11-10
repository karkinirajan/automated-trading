import json
import sys

import pytest
import requests

sys.path.insert(0, "data")
import alphavantage  # noqa: E402
import get_daily_price as daily  # noqa: E402
import get_interdaily_price as hourly  # noqa: E402
import merge_jsonl  # noqa: E402


class TestNormalise:
    RAW = {
        "Meta Data": {"1. Information": "Daily Prices", "2. Symbol": "AAPL"},
        "Time Series (Daily)": {
            "2025-10-01": {"1. open": "10", "2. high": "12", "3. low": "9", "4. close": "11", "5. volume": "100"},
            "2025-10-02": {"1. open": "20", "2. high": "22", "3. low": "19", "4. close": "21", "5. volume": "200"},
        },
    }

    def run(self, raw=None):
        import copy

        return merge_jsonl.normalise(copy.deepcopy(raw or self.RAW))

    def test_open_and_close_are_renamed(self):
        day = self.run()["Time Series (Daily)"]["2025-10-01"]
        assert day == {"1. buy price": "10", "2. high": "12", "3. low": "9", "4. sell price": "11", "5. volume": "100"}

    def test_the_latest_bar_keeps_only_its_open(self):
        assert self.run()["Time Series (Daily)"]["2025-10-02"] == {"1. buy price": "20"}

    def test_a_latest_bar_without_an_open_becomes_empty(self):
        raw = {"Meta Data": {}, "Time Series (Daily)": {"2025-10-01": {"2. high": "1"}}}
        assert self.run(raw)["Time Series (Daily)"]["2025-10-01"] == {}

    def test_the_description_is_updated(self):
        assert self.run()["Meta Data"]["1. Information"] == "Daily Prices (buy price, high, low, sell price) and Volumes"

    def test_the_latest_is_the_greatest_timestamp_not_the_last_key(self):
        raw = {"Time Series (60min)": {"2025-10-02 15:00:00": {"1. open": "2", "4. close": "3"}, "2025-10-01 10:00:00": {"1. open": "1", "4. close": "1.5"}}}
        series = self.run(raw)["Time Series (60min)"]
        assert series["2025-10-02 15:00:00"] == {"1. buy price": "2"}
        assert series["2025-10-01 10:00:00"] == {"1. buy price": "1", "4. sell price": "1.5"}

    @pytest.mark.parametrize("raw", [{}, {"Meta Data": {}}, {"Time Series (Daily)": {}}, {"Time Series (Daily)": []}, {"Error Message": "x"}])
    def test_a_document_without_a_series_is_returned_unchanged(self, raw):
        assert merge_jsonl.normalise(dict(raw)) == raw

    def test_a_bar_that_is_not_a_mapping_is_left_alone(self):
        raw = {"Time Series (Daily)": {"2025-10-01": "x", "2025-10-02": {"1. open": "5"}}}
        assert self.run(raw)["Time Series (Daily)"]["2025-10-01"] == "x"

    def test_it_is_idempotent(self):
        once = self.run()
        assert merge_jsonl.normalise(json.loads(json.dumps(once))) == once


class TestSymbolOf:
    @pytest.mark.parametrize(
        ("path", "symbol"),
        [("a/daily_prices_AAPL.json", "AAPL"), ("daily_prices_GOOGL.json", "GOOGL"), ("x/daily_prices_ON.json", "ON")],
    )
    def test_members(self, path, symbol):
        assert merge_jsonl.symbol_of(path) == symbol

    @pytest.mark.parametrize("path", ["daily_prices_QQQ.json", "Adaily_prices_QQQ.json", "daily_prices_ZZZZ.json", "prices_AAPL.json", "daily_prices_AAPL.txt", "daily_prices_.json", "daily_prices_AAPLX.json", "notes.json", "daily_1234567AAPL.json"])
    def test_everything_else_is_none(self, path):
        assert merge_jsonl.symbol_of(path) is None


class TestMerge:
    def test_only_member_files_are_merged_in_order(self, tmp_path):
        for symbol in ("MSFT", "AAPL", "QQQ"):
            (tmp_path / f"daily_prices_{symbol}.json").write_text(json.dumps({"Meta Data": {"2. Symbol": symbol}, "Time Series (Daily)": {"2025-10-01": {"1. open": "1", "4. close": "2"}}}))
        (tmp_path / "Adaily_prices_QQQ.json").write_text("{}")
        assert merge_jsonl.merge(str(tmp_path)) == 2
        lines = [json.loads(line) for line in (tmp_path / "merged.jsonl").read_text().splitlines()]
        assert [d["Meta Data"]["2. Symbol"] for d in lines] == ["AAPL", "MSFT"]
        assert lines[0]["Time Series (Daily)"]["2025-10-01"] == {"1. buy price": "1"}

    def test_a_file_that_is_not_an_object_is_skipped(self, tmp_path):
        (tmp_path / "daily_prices_AAPL.json").write_text("[1, 2]")
        assert merge_jsonl.merge(str(tmp_path)) == 0
        assert (tmp_path / "merged.jsonl").read_text() == ""

    def test_the_committed_data_merges_to_the_committed_file(self, tmp_path):
        import shutil
        from pathlib import Path

        real = Path(__file__).resolve().parents[1] / "data"
        for path in real.glob("daily_prices_*.json"):
            shutil.copy(path, tmp_path / path.name)
        merge_jsonl.merge(str(tmp_path))
        assert (tmp_path / "merged.jsonl").read_bytes() == (real / "merged.jsonl").read_bytes()


class FakeResponse:
    def __init__(self, payload=None, status=200, bad_json=False):
        self.payload, self.status, self.bad_json = payload, status, bad_json

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status} for url: https://www.alphavantage.co/query?apikey=SECRET")

    def json(self):
        if self.bad_json:
            raise ValueError("no json")
        return self.payload


@pytest.fixture()
def av(monkeypatch, tmp_path):
    calls, answers = [], []
    monkeypatch.setenv("ALPHAADVANTAGE_API_KEY", "SECRET")
    monkeypatch.setattr(alphavantage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(daily, "DATA_DIR", tmp_path)
    monkeypatch.setattr(hourly, "DATA_DIR", tmp_path)

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(alphavantage.requests, "get", fake_get)
    return calls, answers


class TestFetchSeries:
    def test_the_request_uses_params_a_timeout_and_the_key(self, av):
        calls, answers = av
        answers.append(FakeResponse({"Meta Data": {}}))
        assert alphavantage.fetch_series(function="TIME_SERIES_DAILY", symbol="A&B") == {"Meta Data": {}}
        assert calls[0]["url"] == "https://www.alphavantage.co/query"
        assert calls[0]["params"] == {"function": "TIME_SERIES_DAILY", "symbol": "A&B", "apikey": "SECRET"}
        assert calls[0]["timeout"] == (5, 60)

    def test_a_missing_key_is_an_error(self, av, monkeypatch):
        monkeypatch.delenv("ALPHAADVANTAGE_API_KEY")
        with pytest.raises(RuntimeError, match="ALPHAADVANTAGE_API_KEY"):
            alphavantage.fetch_series(function="x", symbol="A")

    @pytest.mark.parametrize("key", ["Note", "Information", "Error Message"])
    def test_a_refusal_is_none_and_says_why(self, av, capsys, key):
        calls, answers = av
        answers.append(FakeResponse({key: "Thank you for using Alpha Vantage! rate limit"}))
        assert alphavantage.fetch_series(function="x", symbol="AAPL") is None
        assert "refused AAPL: Thank you" in capsys.readouterr().out

    def test_a_network_failure_is_none_and_the_key_is_not_printed(self, av, capsys):
        calls, answers = av
        answers.append(FakeResponse(status=500))
        assert alphavantage.fetch_series(function="x", symbol="AAPL") is None
        out = capsys.readouterr().out
        assert "failed: HTTPError" in out and "SECRET" not in out

    @pytest.mark.parametrize("answer", [requests.ConnectionError("SECRET host"), requests.Timeout("slow"), FakeResponse(bad_json=True)])
    def test_other_failures_are_none(self, av, capsys, answer):
        calls, answers = av
        answers.append(answer)
        assert alphavantage.fetch_series(function="x", symbol="A") is None
        assert "SECRET" not in capsys.readouterr().out

    def test_a_response_that_is_not_an_object_is_none(self, av):
        calls, answers = av
        answers.append(FakeResponse([1, 2]))
        assert alphavantage.fetch_series(function="x", symbol="A") is None


class TestDailyScript:
    def test_a_download_is_saved_next_to_the_scripts(self, av, tmp_path):
        calls, answers = av
        answers.append(FakeResponse({"Time Series (Daily)": {"2025-10-01": {}}}))
        assert daily.get_daily_price("AAPL") is True
        assert json.loads((tmp_path / "daily_prices_AAPL.json").read_text()) == {"Time Series (Daily)": {"2025-10-01": {}}}
        assert calls[0]["params"]["outputsize"] == "compact" and calls[0]["params"]["function"] == "TIME_SERIES_DAILY"

    def test_qqq_is_saved_twice(self, av, tmp_path):
        calls, answers = av
        answers.append(FakeResponse({"Time Series (Daily)": {}}))
        daily.get_daily_price("QQQ")
        assert (tmp_path / "daily_prices_QQQ.json").exists() and (tmp_path / "Adaily_prices_QQQ.json").exists()

    def test_a_refusal_writes_nothing(self, av, tmp_path):
        calls, answers = av
        answers.append(FakeResponse({"Note": "slow down"}))
        assert daily.get_daily_price("AAPL") is False
        assert not list(tmp_path.glob("*.json"))


class TestHourlyScript:
    def test_merge_series_keeps_old_bars_and_prefers_new_ones(self):
        old = {"Meta Data": {"m": 1}, "Time Series (60min)": {"t1": {"v": "old"}, "t2": {"v": "old"}}}
        new = {"Time Series (60min)": {"t2": {"v": "new"}, "t3": {"v": "new"}}}
        assert hourly.merge_series(old, new) == {
            "Meta Data": {"m": 1},
            "Time Series (60min)": {"t1": {"v": "old"}, "t2": {"v": "new"}, "t3": {"v": "new"}},
        }

    def test_the_new_meta_data_wins_when_there_is_one(self):
        merged = hourly.merge_series({"Meta Data": {"m": "old"}}, {"Meta Data": {"m": "new"}, "Time Series (60min)": {}})
        assert merged["Meta Data"] == {"m": "new"}

    def test_the_first_download_is_written_as_it_is(self, av, tmp_path):
        calls, answers = av
        answers.append(FakeResponse({"Time Series (60min)": {"t1": {}}}))
        assert hourly.get_daily_price("AAPL") is True
        assert json.loads((tmp_path / "daily_prices_AAPL.json").read_text()) == {"Time Series (60min)": {"t1": {}}}
        params = calls[0]["params"]
        assert params["function"] == "TIME_SERIES_INTRADAY" and params["interval"] == "60min" and params["extended_hours"] == "false"

    def test_a_later_download_is_merged_into_the_file(self, av, tmp_path):
        calls, answers = av
        (tmp_path / "daily_prices_AAPL.json").write_text(json.dumps({"Time Series (60min)": {"t1": {"v": 1}}}))
        answers.append(FakeResponse({"Time Series (60min)": {"t2": {"v": 2}}}))
        hourly.get_daily_price("AAPL")
        assert json.loads((tmp_path / "daily_prices_AAPL.json").read_text())["Time Series (60min)"] == {"t1": {"v": 1}, "t2": {"v": 2}}

    def test_qqq_goes_into_both_files(self, av, tmp_path):
        calls, answers = av
        (tmp_path / "Adaily_prices_QQQ.json").write_text(json.dumps({"Time Series (60min)": {"t1": {}}}))
        answers.append(FakeResponse({"Time Series (60min)": {"t2": {}}}))
        hourly.get_daily_price("QQQ")
        assert set(json.loads((tmp_path / "Adaily_prices_QQQ.json").read_text())["Time Series (60min)"]) == {"t1", "t2"}
        assert set(json.loads((tmp_path / "daily_prices_QQQ.json").read_text())["Time Series (60min)"]) == {"t2"}

    def test_a_refusal_writes_nothing(self, av, tmp_path):
        calls, answers = av
        answers.append(FakeResponse({"Information": "premium"}))
        assert hourly.get_daily_price("AAPL") is False
        assert not list(tmp_path.glob("*.json"))
