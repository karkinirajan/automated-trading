import json
import math

import pytest

from tests.helpers import bar, write_positions, write_prices
from tools import result_tools as rt


class TestPortfolioValue:
    def test_cash_plus_shares_at_their_prices(self):
        assert rt.calculate_portfolio_value({"CASH": 5, "AAPL": 2, "MSFT": 1}, {"AAPL_price": 10.0, "MSFT_price": 100.0}, 50.0) == 170.0

    def test_cash_entry_in_the_positions_is_not_double_counted(self):
        assert rt.calculate_portfolio_value({"CASH": 1000.0}, {}, 7.0) == 7.0

    def test_a_holding_without_a_price_is_not_counted(self):
        assert rt.calculate_portfolio_value({"AAPL": 2}, {"AAPL_price": None}, 1.0) == 1.0
        assert rt.calculate_portfolio_value({"AAPL": 2}, {}, 1.0) == 1.0

    def test_no_shares_no_value(self):
        assert rt.calculate_portfolio_value({"AAPL": 0}, {"AAPL_price": 10.0}, 0.0) == 0.0

    def test_cash_defaults_to_zero(self):
        assert rt.calculate_portfolio_value({"AAPL": 1}, {"AAPL_price": 3.0}) == 3.0


class TestDailyReturns:
    def test_returns_between_consecutive_dates(self):
        assert rt.calculate_daily_returns({"2025-10-03": 121.0, "2025-10-01": 100.0, "2025-10-02": 110.0}) == pytest.approx([0.1, 0.1])

    def test_fewer_than_two_values(self):
        assert rt.calculate_daily_returns({}) == [] and rt.calculate_daily_returns({"2025-10-01": 5}) == []

    def test_a_zero_value_day_gives_no_return_for_the_next_step(self):
        assert rt.calculate_daily_returns({"a": 0.0, "b": 5.0, "c": 10.0}) == [1.0]

    def test_a_loss(self):
        assert rt.calculate_daily_returns({"a": 100.0, "b": 90.0}) == pytest.approx([-0.1])


class TestSharpe:
    def test_known_value(self):
        returns = [0.01, -0.005, 0.02, 0.0, 0.015]
        import numpy as np

        mean, std = np.mean(returns), np.std(returns, ddof=1)
        assert rt.calculate_sharpe_ratio(returns) == pytest.approx((mean * 252 - 0.02) / (std * math.sqrt(252)))

    def test_a_custom_risk_free_rate(self):
        returns = [0.01, 0.02, 0.0]
        assert rt.calculate_sharpe_ratio(returns, 0.0) > rt.calculate_sharpe_ratio(returns, 0.05)

    @pytest.mark.parametrize("returns", [[], [0.01], [0.01, 0.01, 0.01]])
    def test_too_little_data_or_no_variation_is_zero(self, returns):
        assert rt.calculate_sharpe_ratio(returns) == 0.0

    def test_losses_give_a_negative_ratio(self):
        assert rt.calculate_sharpe_ratio([-0.01, -0.02, -0.005]) < 0


class TestDrawdown:
    def test_the_deepest_fall_from_a_peak(self):
        drawdown, start, end = rt.calculate_max_drawdown({"d1": 100.0, "d2": 120.0, "d3": 90.0, "d4": 110.0})
        assert drawdown == pytest.approx(0.25)
        assert (start, end) == ("d2", "d3")

    def test_a_rising_series_has_none(self):
        assert rt.calculate_max_drawdown({"a": 1.0, "b": 2.0, "c": 3.0}) == (0.0, "", "")

    def test_the_first_value_is_the_first_peak(self):
        assert rt.calculate_max_drawdown({"a": 100.0, "b": 50.0}) == (0.5, "a", "b")

    def test_a_later_deeper_fall_replaces_an_earlier_one(self):
        drawdown, start, end = rt.calculate_max_drawdown({"a": 100.0, "b": 90.0, "c": 200.0, "d": 100.0})
        assert (drawdown, start, end) == (0.5, "c", "d")

    def test_dates_are_taken_in_order_whatever_the_dict_order(self):
        assert rt.calculate_max_drawdown({"c": 90.0, "a": 100.0, "b": 120.0}) == pytest.approx((0.25, "b", "c"))

    def test_an_empty_portfolio(self):
        assert rt.calculate_max_drawdown({}) == (0.0, "", "")

    def test_a_portfolio_that_is_always_worth_nothing_does_not_divide_by_zero(self):
        assert rt.calculate_max_drawdown({"a": 0.0, "b": 0.0}) == (0.0, "", "")


class TestCumulativeAndAnnualized:
    def test_cumulative(self):
        assert rt.calculate_cumulative_return({"2025-10-02": 120.0, "2025-10-01": 100.0}) == pytest.approx(0.2)
        assert rt.calculate_cumulative_return({"a": 100.0, "b": 80.0}) == pytest.approx(-0.2)

    def test_cumulative_edge_cases(self):
        assert rt.calculate_cumulative_return({}) == 0.0
        assert rt.calculate_cumulative_return({"a": 0.0, "b": 5.0}) == 0.0
        assert rt.calculate_cumulative_return({"a": 5.0}) == 0.0

    def test_annualized_over_days(self):
        # +10% over 73 days -> (1.1) ** 5 - 1
        values = {"2025-01-01": 100.0, "2025-03-15": 110.0}
        assert rt.calculate_annualized_return(values) == pytest.approx(1.1**5 - 1)

    def test_annualized_over_hours(self):
        # the hourly runs store timestamps: this used to crash with "unconverted data remains"
        values = {"2025-10-01 10:00:00": 100.0, "2025-10-02 10:00:00": 101.0}
        assert rt.calculate_annualized_return(values) == pytest.approx(1.01**365 - 1)

    def test_annualized_over_a_part_of_a_day(self):
        values = {"2025-10-01 10:00:00": 100.0, "2025-10-01 16:00:00": 100.5}
        assert rt.calculate_annualized_return(values) == pytest.approx(1.005 ** (365 / 0.25) - 1)

    @pytest.mark.parametrize(
        "values",
        [{}, {"2025-10-01": 100.0}, {"2025-10-01": 0.0, "2025-10-02": 5.0}, {"2025-10-01": 100.0, "2025-10-01 ": 100.0}, {"bad": 1.0, "worse": 2.0}],
    )
    def test_nothing_to_annualize(self, values):
        assert rt.calculate_annualized_return(values) == 0.0

    def test_a_huge_move_over_a_few_hours_does_not_overflow(self):
        # +50% in two hours, annualised, is 1.5 ** 4380: past what a float can hold. It used to raise OverflowError.
        assert rt.calculate_annualized_return({"2025-10-01 10:00:00": 100.0, "2025-10-01 12:00:00": 150.0}) == 0.0

    def test_two_keys_for_the_same_moment_is_zero_not_a_division_by_zero(self):
        assert rt.calculate_annualized_return({"2025-10-01": 1.0, "2025-10-01 00:00:00": 2.0}) == 0.0

    def test_an_unreadable_timestamp_is_zero(self):
        assert rt.calculate_annualized_return({"2025-10-01 10:00:00": 1.0, "2025-10-01 10:00:00x": 2.0}) == 0.0


class TestVolatilityAndRatios:
    def test_volatility_is_annualized(self):
        import numpy as np

        returns = [0.01, -0.02, 0.03, 0.0]
        assert rt.calculate_volatility(returns) == pytest.approx(np.std(returns, ddof=1) * math.sqrt(252))

    @pytest.mark.parametrize("returns", [[], [0.1]])
    def test_volatility_needs_two_returns(self, returns):
        assert rt.calculate_volatility(returns) == 0.0

    def test_win_rate(self):
        assert rt.calculate_win_rate([0.1, -0.1, 0.0, 0.2]) == 0.5
        assert rt.calculate_win_rate([]) == 0.0
        assert rt.calculate_win_rate([-1.0]) == 0.0
        assert rt.calculate_win_rate([0.5]) == 1.0

    def test_profit_loss_ratio(self):
        assert rt.calculate_profit_loss_ratio([0.1, 0.3, -0.1]) == pytest.approx(2.0)
        assert rt.calculate_profit_loss_ratio([0.2, -0.05, -0.15]) == pytest.approx(2.0)

    @pytest.mark.parametrize("returns", [[], [0.1, 0.2], [-0.1, -0.2], [0.0, 0.0]])
    def test_profit_loss_ratio_needs_both_wins_and_losses(self, returns):
        assert rt.calculate_profit_loss_ratio(returns) == 0.0


@pytest.fixture()
def history(project, agent):
    write_prices(
        project,
        {
            "AAPL": {"2025-10-01": bar(99, 100), "2025-10-02": bar(100, 110), "2025-10-06": bar(112, 120), "2025-10-07": {"1. buy price": "121"}},
            "MSFT": {"2025-10-01": bar(199, 200), "2025-10-02": bar(200, 190), "2025-10-06": bar(190, 195), "2025-10-07": {"1. buy price": "196"}},
        },
    )
    write_positions(
        agent,
        [
            {"date": "2025-10-01", "id": 0, "positions": {"CASH": 1000.0, "AAPL": 0, "MSFT": 0}},
            {"date": "2025-10-02", "id": 1, "positions": {"CASH": 800.0, "AAPL": 2, "MSFT": 0}},
            {"date": "2025-10-02", "id": 2, "positions": {"CASH": 600.0, "AAPL": 2, "MSFT": 1}},
            {"date": "2025-10-03", "id": 3, "positions": {"CASH": 600.0, "AAPL": 2, "MSFT": 1}},
            {"date": "2025-10-06", "id": 4, "positions": {"CASH": 600.0, "AAPL": 2, "MSFT": 1}},
            {"date": "2025-10-07", "id": 5, "positions": {"CASH": 600.0, "AAPL": 2, "MSFT": 1}},
        ],
    )


class TestDailyPortfolioValues:
    def test_each_day_uses_the_last_record_and_that_days_close(self, history):
        values = rt.get_daily_portfolio_values("bot")
        assert values["2025-10-01"] == 1000.0
        assert values["2025-10-02"] == 600.0 + 2 * 110 + 1 * 190  # the id-2 record, valued at the 10-02 closes

    def test_a_day_with_no_prices_uses_the_last_known_close_not_zero(self, history):
        values = rt.get_daily_portfolio_values("bot")
        # 10-03 had no market data: the holdings keep their 10-02 value (a missing close used to count as worth nothing)
        assert values["2025-10-03"] == 600.0 + 2 * 110 + 190

    def test_the_latest_bar_has_no_close_and_uses_the_previous_one(self, history):
        values = rt.get_daily_portfolio_values("bot")
        assert values["2025-10-07"] == 600.0 + 2 * 120 + 195

    def test_a_date_range(self, history):
        assert sorted(rt.get_daily_portfolio_values("bot", "2025-10-02", "2025-10-03")) == ["2025-10-02", "2025-10-03"]
        assert sorted(rt.get_daily_portfolio_values("bot", start_date="2025-10-06")) == ["2025-10-06", "2025-10-07"]
        assert sorted(rt.get_daily_portfolio_values("bot", end_date="2025-10-01")) == ["2025-10-01"]

    def test_a_holding_valued_before_any_price_exists_is_not_counted(self, project, agent):
        write_prices(project, {"AAPL": {"2025-10-05": bar(1, 2)}})
        write_positions(agent, [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 10.0, "AAPL": 3}}])
        assert rt.get_daily_portfolio_values("bot") == {"2025-10-01": 10.0}

    def test_missing_files(self, project, agent):
        assert rt.get_daily_portfolio_values("bot") == {}
        assert rt.get_daily_portfolio_values("nobody") == {}

    def test_damaged_lines_are_skipped(self, history, agent):
        with (agent / "position" / "position.jsonl").open("a") as f:
            f.write("garbage\n\n")
        assert "2025-10-01" in rt.get_daily_portfolio_values("bot")

    def test_available_date_range(self, history):
        assert rt.get_available_date_range("bot") == ("2025-10-01", "2025-10-07")
        assert rt.get_available_date_range("nobody") == ("", "")

    def test_an_empty_history(self, agent):
        (agent / "position").mkdir()
        (agent / "position" / "position.jsonl").write_text("\n")
        assert rt.get_available_date_range("bot") == ("", "")


class TestAllMetrics:
    def test_a_full_report(self, history):
        m = rt.calculate_all_metrics("bot")
        assert m["start_date"] == "2025-10-01" and m["end_date"] == "2025-10-07" and m["total_trading_days"] == 5  # six records, five distinct days
        first, last = 1000.0, 600.0 + 2 * 120 + 195
        assert m["cumulative_return"] == round((last - first) / first, 4)
        assert 0.0 <= m["max_drawdown"] < 1.0
        assert set(m) >= {"sharpe_ratio", "volatility", "win_rate", "profit_loss_ratio", "annualized_return", "portfolio_values", "daily_returns"}
        assert len(m["daily_returns"]) == 4

    def test_no_history_is_an_error_entry_with_zeroed_metrics(self, project, agent):
        m = rt.calculate_all_metrics("bot")
        assert m["error"] == "Unable to get available data date range" and m["sharpe_ratio"] == 0.0 and m["total_trading_days"] == 0

    def test_a_range_with_no_data(self, history):
        m = rt.calculate_all_metrics("bot", "2030-01-01", "2030-02-01")
        assert m["error"] == "Unable to get portfolio data"

    def test_the_hourly_history_does_not_crash(self, project, agent):
        write_prices(project, {"AAPL": {"2025-10-01 10:00:00": bar(1, 2), "2025-10-01 11:00:00": bar(2, 3), "2025-10-01 12:00:00": {"1. buy price": "3"}}}, hourly=True)
        write_positions(
            agent,
            [{"date": f"2025-10-01 {h}:00:00", "id": i, "positions": {"CASH": 0.0, "AAPL": 10}} for i, h in enumerate(["10", "11", "12"])],
        )
        m = rt.calculate_all_metrics("bot")
        assert m["total_trading_days"] == 3 and m["portfolio_values"]["2025-10-01 12:00:00"] == 30.0  # the last bar's missing close: carried from 11:00


class TestSavedMetrics:
    def test_ids_count_up_and_records_round_trip(self, history, tmp_path):
        out = tmp_path / "metrics"
        m = rt.calculate_all_metrics("bot")
        path = rt.save_metrics_to_jsonl(m, "bot", str(out))
        rt.save_metrics_to_jsonl(m, "bot", str(out))
        lines = [json.loads(line) for line in open(path)]
        assert [r["id"] for r in lines] == [0, 1]
        assert lines[0]["model_name"] == "bot"
        assert lines[0]["performance_metrics"]["sharpe_ratio"] == m["sharpe_ratio"]
        assert lines[0]["portfolio_summary"]["initial_value"] == 1000.0
        assert rt.get_latest_metrics("bot", str(out))["id"] == 1
        assert [r["id"] for r in rt.get_metrics_history("bot", str(out))] == [0, 1]
        assert [r["id"] for r in rt.get_metrics_history("bot", str(out), limit=1)] == [1]

    def test_the_default_folder_is_inside_the_agent_folder(self, history, agent):
        path = rt.save_metrics_to_jsonl(rt.calculate_all_metrics("bot"), "bot")
        assert path == str(agent / "metrics" / "performance_metrics.jsonl")

    def test_no_history(self, tmp_path):
        assert rt.get_latest_metrics("bot", str(tmp_path / "none")) is None
        assert rt.get_metrics_history("bot", str(tmp_path / "none")) == []

    def test_a_zero_initial_value_gives_no_percentage(self, tmp_path):
        path = rt.save_metrics_to_jsonl({"portfolio_values": {"a": 0.0, "b": 5.0}}, "bot", str(tmp_path))
        assert json.loads(open(path).read())["portfolio_summary"]["value_change_percent"] == 0.0

    def test_calculate_and_save(self, history, tmp_path, capsys):
        m = rt.calculate_and_save_metrics("bot", output_dir=str(tmp_path), print_report=True)
        assert "Portfolio Performance Report" in capsys.readouterr().out
        assert m["record_id"] == 0 and (tmp_path / "performance_metrics.jsonl").exists()

    def test_calculate_and_save_without_a_report(self, history, tmp_path, capsys):
        rt.calculate_and_save_metrics("bot", output_dir=str(tmp_path), print_report=False)
        assert "Performance Report" not in capsys.readouterr().out

    def test_the_report_of_an_error(self, project, agent, capsys):
        rt.print_performance_report(rt.calculate_all_metrics("bot"))
        assert "Error: Unable to get available data date range" in capsys.readouterr().out
