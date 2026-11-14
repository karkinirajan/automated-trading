import json

import pytest

from tests.helpers import bar, read_positions, write_positions, write_prices
from tools.price_tools import (
    add_no_trade_record,
    get_latest_position,
    get_open_prices,
    get_today_init_position,
    get_yesterday_date,
    get_yesterday_open_and_close_price,
    get_yesterday_profit,
)


@pytest.fixture()
def prices(project):
    write_prices(
        project,
        {
            "AAPL": {"2025-10-01": bar(100, 101), "2025-10-02": bar(102, 103), "2025-10-06": bar(104, 105)},
            "MSFT": {"2025-10-01": bar(200, 201), "2025-10-02": bar(None, 203), "2025-10-06": bar("bad", None)},
        },
    )


class TestYesterdayDate:
    def test_the_previous_day_in_the_data(self, prices):
        assert get_yesterday_date("2025-10-02") == "2025-10-01"

    def test_it_skips_days_with_no_data(self, prices):
        assert get_yesterday_date("2025-10-06") == "2025-10-02"  # the weekend is not in the data

    def test_the_input_day_itself_is_not_the_answer(self, prices):
        assert get_yesterday_date("2025-10-06") != "2025-10-06"

    def test_after_the_last_day_it_is_the_last_day(self, prices):
        assert get_yesterday_date("2025-12-31") == "2025-10-06"

    def test_before_the_first_day_it_steps_back_over_the_weekend(self, prices):
        assert get_yesterday_date("2025-09-29") == "2025-09-26"  # Monday: back past Sunday and Saturday to Friday

    def test_a_date_with_no_data_file_steps_back_one_weekday(self, project):
        assert get_yesterday_date("2025-10-02") == "2025-10-01"
        assert get_yesterday_date("2025-10-06") == "2025-10-03"  # Monday -> Friday

    def test_a_time_steps_back_one_hour_when_the_data_has_none(self, project):
        assert get_yesterday_date("2025-10-02 10:00:00") == "2025-10-02 09:00:00"

    def test_hourly_data(self, project):
        write_prices(project, {"AAPL": {"2025-10-02 10:00:00": bar(1), "2025-10-02 11:00:00": bar(2), "2025-10-02 15:00:00": bar(3)}}, hourly=True)
        assert get_yesterday_date("2025-10-02 15:00:00") == "2025-10-02 11:00:00"
        assert get_yesterday_date("2025-10-02 11:00:00") == "2025-10-02 10:00:00"
        assert get_yesterday_date("2025-10-02 10:00:00") == "2025-10-02 09:00:00"  # nothing earlier: one hour back

    def test_a_date_input_ignores_the_time_of_day_in_the_data(self, project):
        write_prices(project, {"AAPL": {"2025-10-02 10:00:00": bar(1), "2025-10-03 10:00:00": bar(2)}}, hourly=True)
        assert get_yesterday_date("2025-10-03") == "2025-10-02"

    def test_a_custom_file(self, tmp_path):
        other = tmp_path / "o.jsonl"
        other.write_text(json.dumps({"Meta Data": {"2. Symbol": "A"}, "Time Series (Daily)": {"2025-01-02": {}, "2025-01-03": {}}}) + "\n")
        assert get_yesterday_date("2025-01-03", str(other)) == "2025-01-02"

    def test_damaged_lines_and_odd_documents_are_skipped(self, project):
        (project / "merged.jsonl").write_text(
            "\n".join(
                [
                    "not json",
                    "",
                    "[1, 2]",
                    json.dumps({"no": "meta"}),
                    json.dumps({"Meta Data": {"2. Symbol": "A"}, "Time Series (Daily)": {"2025-10-01": {}, "garbage": {}, "2025-10-02": {}}}),
                ]
            )
        )
        assert get_yesterday_date("2025-10-02") == "2025-10-01"

    def test_both_timestamp_shapes_in_one_series(self, project):
        write_prices(project, {"A": {"2025-10-01": {}, "2025-10-02 09:00:00": {}}})
        assert get_yesterday_date("2025-10-03") == "2025-10-02"


class TestOpenPrices:
    def test_the_open_of_each_symbol(self, prices):
        assert get_open_prices("2025-10-01", ["AAPL", "MSFT"]) == {"AAPL_price": 100.0, "MSFT_price": 200.0}

    def test_a_symbol_not_asked_for_is_left_out(self, prices):
        assert get_open_prices("2025-10-01", ["AAPL"]) == {"AAPL_price": 100.0}

    def test_a_date_with_no_bar_is_absent(self, prices):
        assert get_open_prices("2025-10-03", ["AAPL"]) == {}

    def test_a_bar_without_an_open_is_none(self, prices):
        assert get_open_prices("2025-10-02", ["MSFT"]) == {"MSFT_price": None}

    def test_an_unreadable_open_is_none(self, prices):
        assert get_open_prices("2025-10-06", ["MSFT"]) == {"MSFT_price": None}

    def test_an_unknown_symbol_is_absent(self, prices):
        assert get_open_prices("2025-10-01", ["ZZZ"]) == {}

    def test_no_price_file_is_an_empty_answer(self, project):
        assert get_open_prices("2025-10-01", ["AAPL"]) == {}

    def test_the_symbol_list_may_be_empty(self, prices):
        assert get_open_prices("2025-10-01", []) == {}

    def test_a_series_that_is_not_a_mapping_is_skipped(self, project):
        (project / "merged.jsonl").write_text(json.dumps({"Meta Data": {"2. Symbol": "A"}, "Time Series (Daily)": [1]}) + "\n")
        assert get_open_prices("2025-10-01", ["A"]) == {}

    def test_a_bar_that_is_not_a_mapping_is_skipped(self, project):
        write_prices(project, {"A": {"2025-10-01": "oops"}})
        assert get_open_prices("2025-10-01", ["A"]) == {}


class TestYesterdayPrices:
    def test_open_and_close_of_the_previous_day(self, prices):
        opens, closes = get_yesterday_open_and_close_price("2025-10-02", ["AAPL", "MSFT"])
        assert opens == {"AAPL_price": 100.0, "MSFT_price": 200.0}
        assert closes == {"AAPL_price": 101.0, "MSFT_price": 201.0}

    def test_a_previous_day_across_a_weekend(self, prices):
        opens, closes = get_yesterday_open_and_close_price("2025-10-06", ["AAPL"])
        assert opens == {"AAPL_price": 102.0} and closes == {"AAPL_price": 103.0}

    def test_a_half_known_bar_is_none_for_both(self, prices):
        opens, closes = get_yesterday_open_and_close_price("2025-10-06", ["MSFT"])  # 10-02: no open
        assert opens == {"MSFT_price": None} and closes == {"MSFT_price": None}

    def test_no_bar_yesterday_is_none(self, project):
        write_prices(project, {"A": {"2025-10-01": bar(1, 2)}, "B": {"2025-10-02": bar(3, 4)}})
        opens, closes = get_yesterday_open_and_close_price("2025-10-02", ["A", "B"])
        assert opens == {"A_price": 1.0, "B_price": None} and closes == {"A_price": 2.0, "B_price": None}

    def test_symbols_not_asked_for_are_left_out(self, prices):
        assert get_yesterday_open_and_close_price("2025-10-02", ["AAPL"])[0] == {"AAPL_price": 100.0}

    def test_a_custom_file_is_used_for_the_date_too(self, tmp_path):
        other = tmp_path / "o.jsonl"
        other.write_text(json.dumps({"Meta Data": {"2. Symbol": "A"}, "Time Series (Daily)": {"2025-01-02": bar(5, 6), "2025-01-03": bar(7)}}) + "\n")
        opens, closes = get_yesterday_open_and_close_price("2025-01-03", ["A"], str(other))
        assert opens == {"A_price": 5.0} and closes == {"A_price": 6.0}


class TestYesterdayProfit:
    def test_close_minus_open_times_shares(self):
        profit = get_yesterday_profit("2025-10-02", {"AAPL_price": 100.0}, {"AAPL_price": 103.5}, {"AAPL": 10})
        assert profit["AAPL"] == 35.0

    def test_a_loss(self):
        assert get_yesterday_profit("d", {"AAPL_price": 100.0}, {"AAPL_price": 90.0}, {"AAPL": 2})["AAPL"] == -20.0

    def test_no_shares_no_profit(self):
        assert get_yesterday_profit("d", {"AAPL_price": 1.0}, {"AAPL_price": 5.0}, {"AAPL": 0})["AAPL"] == 0.0
        assert get_yesterday_profit("d", {"AAPL_price": 1.0}, {"AAPL_price": 5.0}, {})["AAPL"] == 0.0

    def test_a_missing_price_means_no_profit(self):
        assert get_yesterday_profit("d", {"AAPL_price": None}, {"AAPL_price": 5.0}, {"AAPL": 3})["AAPL"] == 0.0
        assert get_yesterday_profit("d", {"AAPL_price": 1.0}, {}, {"AAPL": 3})["AAPL"] == 0.0

    def test_rounded_to_four_decimals(self):
        assert get_yesterday_profit("d", {"AAPL_price": 1.0}, {"AAPL_price": 1.123456}, {"AAPL": 1})["AAPL"] == 0.1235

    def test_every_nasdaq_symbol_has_an_entry(self):
        from tools.constants import NASDAQ_100_SYMBOLS

        assert set(get_yesterday_profit("d", {}, {}, {})) == set(NASDAQ_100_SYMBOLS)


class TestPositions:
    @pytest.fixture()
    def history(self, agent, prices):
        write_positions(
            agent,
            [
                {"date": "2025-10-01", "id": 0, "positions": {"CASH": 1000.0}},
                {"date": "2025-10-01", "id": 2, "positions": {"CASH": 800.0, "AAPL": 2}},
                {"date": "2025-10-01", "id": 1, "positions": {"CASH": 900.0, "AAPL": 1}},
                {"date": "2025-10-02", "id": 3, "positions": {"CASH": 700.0, "AAPL": 3}},
            ],
        )

    def test_the_latest_position_is_todays_highest_id(self, history):
        assert get_latest_position("2025-10-02", "bot") == ({"CASH": 700.0, "AAPL": 3}, 3)

    def test_without_a_record_today_it_is_the_previous_days_highest_id(self, history):
        assert get_latest_position("2025-10-06", "bot") == ({"CASH": 700.0, "AAPL": 3}, 3)
        assert get_latest_position("2025-10-02", "bot")[1] == 3

    def test_the_highest_id_wins_whatever_the_line_order(self, history):
        assert get_latest_position("2025-10-01", "bot") == ({"CASH": 800.0, "AAPL": 2}, 2)

    def test_no_history_at_all(self, agent, prices):
        assert get_latest_position("2025-10-02", "bot") == ({}, -1)
        assert get_latest_position("2025-10-02", "nobody") == ({}, -1)

    def test_a_history_with_no_usable_day(self, agent, prices):
        write_positions(agent, [{"date": "2025-09-01", "id": 0, "positions": {"CASH": 5.0}}])
        assert get_latest_position("2025-10-02", "bot") == ({}, -1)

    def test_a_record_without_an_id_counts_as_minus_one_for_the_latest_and_zero_for_the_start(self, agent, prices):
        write_positions(agent, [{"date": "2025-10-02", "positions": {"CASH": 5.0}}])
        assert get_latest_position("2025-10-02", "bot") == ({}, -1)
        assert get_today_init_position("2025-10-06", "bot") == {"CASH": 5.0}

    def test_a_record_with_id_zero_is_still_todays(self, agent, prices):
        write_positions(
            agent,
            [
                {"date": "2025-10-01", "id": 5, "positions": {"CASH": 111.0}},
                {"date": "2025-10-02", "id": 0, "positions": {"CASH": 222.0}},
            ],
        )
        assert get_latest_position("2025-10-02", "bot") == ({"CASH": 222.0}, 0)

    def test_the_start_of_the_day_is_the_previous_days_last_position(self, history):
        assert get_today_init_position("2025-10-02", "bot") == {"CASH": 800.0, "AAPL": 2}
        assert get_today_init_position("2025-10-06", "bot") == {"CASH": 700.0, "AAPL": 3}

    def test_the_start_of_the_day_with_no_history(self, agent, prices):
        assert get_today_init_position("2025-10-02", "bot") == {}
        assert get_today_init_position("2025-10-02", "nobody") == {}

    def test_damaged_lines_are_skipped(self, agent, prices):
        path = agent / "position" / "position.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text('oops\n\n{"date": "2025-10-02", "id": 4, "positions": {"CASH": 1.0}}\n[1]\n{"date": "2025-10-02", "id": "x", "positions": {"CASH": 9.0}}\n')
        assert get_latest_position("2025-10-02", "bot") == ({"CASH": 1.0}, 4)

    def test_an_unsafe_signature_is_refused(self, prices):
        with pytest.raises(ValueError):
            get_latest_position("2025-10-02", "../x")
        with pytest.raises(ValueError):
            get_today_init_position("2025-10-02", "../x")


class TestNoTradeRecord:
    def test_the_latest_position_is_carried_forward(self, agent, prices):
        write_positions(agent, [{"date": "2025-10-01", "id": 4, "positions": {"CASH": 500.0, "AAPL": 2}}])
        add_no_trade_record("2025-10-02", "bot")
        assert read_positions(agent)[-1] == {
            "date": "2025-10-02",
            "id": 5,
            "this_action": {"action": "no_trade", "symbol": "", "amount": 0},
            "positions": {"CASH": 500.0, "AAPL": 2},
        }

    def test_a_second_record_the_same_day_continues_the_ids(self, agent, prices):
        write_positions(agent, [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 5.0}}])
        add_no_trade_record("2025-10-02", "bot")
        add_no_trade_record("2025-10-02", "bot")
        assert [r["id"] for r in read_positions(agent)] == [0, 1, 2]

    def test_an_agent_with_nothing_to_carry_forward_is_an_error_not_an_empty_record(self, agent, prices):
        write_positions(agent, [{"date": "2025-09-01", "id": 0, "positions": {"CASH": 5.0}}])
        with pytest.raises(ValueError, match="no position to carry forward"):
            add_no_trade_record("2025-10-02", "bot")
        assert len(read_positions(agent)) == 1

    def test_an_agent_with_no_file_is_an_error_too(self, agent, prices):
        with pytest.raises(ValueError):
            add_no_trade_record("2025-10-02", "bot")
