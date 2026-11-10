import json
import threading

import pytest

from tests.helpers import bar, read_positions, write_positions, write_prices
from tools import trading
from tools.trading import MAX_AMOUNT, TradeError, apply_buy, apply_sell, execute_trade, validate_amount

POSITION = {"CASH": 10000.0, "AAPL": 0, "MSFT": 5}


class TestValidateAmount:
    @pytest.mark.parametrize("amount", [1, 2, 100, MAX_AMOUNT])
    def test_accepted(self, amount):
        assert validate_amount(amount) == amount

    @pytest.mark.parametrize("amount", [0, -1, -100, MAX_AMOUNT + 1, 10**12])
    def test_out_of_range(self, amount):
        with pytest.raises(TradeError, match=f"between 1 and {MAX_AMOUNT}"):
            validate_amount(amount)

    @pytest.mark.parametrize("amount", [1.0, 1.5, 0.5, "5", None, True, False, [1], float("nan")])
    def test_must_be_a_whole_number(self, amount):
        with pytest.raises(TradeError, match="whole number"):
            validate_amount(amount)

    def test_the_error_carries_the_message_for_the_agent(self):
        with pytest.raises(TradeError) as exc:
            validate_amount(-5)
        assert "error" in exc.value.payload and "This action will not be allowed" in exc.value.payload["error"]


class TestApplyBuy:
    def test_moves_cash_into_shares(self):
        assert apply_buy(POSITION, "AAPL", 10, 150.0) == {"CASH": 8500.0, "AAPL": 10, "MSFT": 5}

    def test_the_old_position_is_not_changed(self):
        before = dict(POSITION)
        apply_buy(POSITION, "AAPL", 10, 150.0)
        assert POSITION == before

    def test_adds_to_an_existing_holding(self):
        assert apply_buy(POSITION, "MSFT", 2, 100.0)["MSFT"] == 7

    def test_a_symbol_not_yet_in_the_position_starts_at_zero(self):
        assert apply_buy(POSITION, "NVDA", 1, 100.0)["NVDA"] == 1

    def test_spending_exactly_all_the_cash_is_allowed(self):
        assert apply_buy({"CASH": 1000.0}, "AAPL", 10, 100.0) == {"CASH": 0.0, "AAPL": 10}

    def test_one_cent_too_much_is_refused(self):
        with pytest.raises(TradeError, match="Insufficient cash") as exc:
            apply_buy({"CASH": 999.99}, "AAPL", 10, 100.0)
        assert exc.value.payload["required_cash"] == 1000.0
        assert exc.value.payload["cash_available"] == 999.99

    def test_floating_point_drift_does_not_refuse_an_affordable_order(self):
        # 3 * 0.1 is 0.30000000000000004 in binary floating point: one part in 10**17 more than the 0.3 the account holds
        assert 3 * 0.1 > 0.3
        assert apply_buy({"CASH": 0.3}, "AAPL", 3, 0.1)["CASH"] == 0.0

    def test_a_real_shortfall_is_still_refused(self):
        with pytest.raises(TradeError, match="Insufficient cash"):
            apply_buy({"CASH": 0.3}, "AAPL", 3, 0.1000001)

    def test_cash_is_rounded_to_six_decimals(self):
        assert apply_buy({"CASH": 100.123456789}, "AAPL", 1, 1.0)["CASH"] == 99.123457

    @pytest.mark.parametrize("amount", [-1, -1000, 0])
    def test_a_negative_or_zero_amount_is_not_a_way_to_make_money(self, amount):
        with pytest.raises(TradeError):
            apply_buy(POSITION, "AAPL", amount, 150.0)

    @pytest.mark.parametrize("price", [None, 0, -5, float("nan"), float("inf"), "100", True])
    def test_a_missing_or_impossible_price_is_refused(self, price):
        with pytest.raises(TradeError, match="Price is not available"):
            apply_buy(POSITION, "AAPL", 1, price)

    def test_no_cash_entry_means_no_cash(self):
        with pytest.raises(TradeError, match="Insufficient cash"):
            apply_buy({"AAPL": 0}, "AAPL", 1, 10.0)

    def test_an_integer_price_works(self):
        assert apply_buy(POSITION, "AAPL", 2, 100)["CASH"] == 9800.0


class TestApplySell:
    def test_moves_shares_into_cash(self):
        assert apply_sell(POSITION, "MSFT", 3, 200.0) == {"CASH": 10600.0, "AAPL": 0, "MSFT": 2}

    def test_the_old_position_is_not_changed(self):
        before = dict(POSITION)
        apply_sell(POSITION, "MSFT", 3, 200.0)
        assert POSITION == before

    def test_selling_everything_is_allowed(self):
        assert apply_sell(POSITION, "MSFT", 5, 100.0)["MSFT"] == 0

    def test_one_share_too_many_is_refused(self):
        with pytest.raises(TradeError, match="Insufficient shares") as exc:
            apply_sell(POSITION, "MSFT", 6, 100.0)
        assert exc.value.payload["have"] == 5 and exc.value.payload["want_to_sell"] == 6

    def test_a_symbol_never_held_is_refused(self):
        with pytest.raises(TradeError, match="No position for NVDA"):
            apply_sell(POSITION, "NVDA", 1, 100.0)

    @pytest.mark.parametrize("amount", [-1, -1000, 0])
    def test_a_negative_amount_cannot_buy_shares_without_cash(self, amount):
        with pytest.raises(TradeError):
            apply_sell(POSITION, "MSFT", amount, 100.0)

    @pytest.mark.parametrize("price", [None, 0, -5, float("nan"), float("inf")])
    def test_a_missing_or_impossible_price_is_refused(self, price):
        with pytest.raises(TradeError, match="Price is not available"):
            apply_sell(POSITION, "MSFT", 1, price)

    def test_cash_is_rounded_to_six_decimals(self):
        assert apply_sell({"CASH": 0.0, "A": 3}, "A", 3, 33.3333333333)["CASH"] == round(3 * 33.3333333333, 6)

    def test_a_missing_cash_entry_starts_at_zero(self):
        assert apply_sell({"A": 2}, "A", 2, 10.0)["CASH"] == 20.0


@pytest.fixture()
def account(project, agent, settings):
    """A funded account on 2025-10-01, and prices for 2025-10-01 and 2025-10-02."""
    write_positions(agent, [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 1000.0, "AAPL": 0, "MSFT": 5}}])
    write_prices(
        project,
        {
            "AAPL": {"2025-10-01": bar(99, 100), "2025-10-02": bar(100)},
            "MSFT": {"2025-10-01": bar(199, 200), "2025-10-02": bar(200, None)},
            "NODATA": {"2025-10-01": bar(None, 5), "2025-10-02": bar(None)},
        },
    )
    settings(today="2025-10-02")
    return agent


def trade(action, symbol, amount, today="2025-10-02", **kw):
    return execute_trade(action, symbol, amount, signature="bot", today_date=today, **kw)


class TestExecuteTrade:
    def test_a_buy_is_recorded_with_the_next_id_and_the_action(self, account):
        result = trade("buy", "AAPL", 4)
        assert result == {"CASH": 600.0, "AAPL": 4, "MSFT": 5}
        records = read_positions(account)
        assert records[-1] == {
            "date": "2025-10-02",
            "id": 1,
            "this_action": {"action": "buy", "symbol": "AAPL", "amount": 4},
            "positions": {"CASH": 600.0, "AAPL": 4, "MSFT": 5},
        }
        assert len(records) == 2

    def test_the_trade_uses_todays_opening_price(self, account):
        assert trade("buy", "AAPL", 1)["CASH"] == 900.0  # the 2025-10-02 open (100), not yesterday's close (100) or open (99)

    def test_a_sell_adds_cash(self, account):
        result = trade("sell", "MSFT", 2)
        assert result == {"CASH": 1400.0, "AAPL": 0, "MSFT": 3}
        assert read_positions(account)[-1]["this_action"] == {"action": "sell", "symbol": "MSFT", "amount": 2}

    def test_ids_keep_counting_within_a_day(self, account):
        trade("buy", "AAPL", 1)
        trade("buy", "AAPL", 1)
        assert [r["id"] for r in read_positions(account)] == [0, 1, 2]
        assert read_positions(account)[-1]["positions"]["CASH"] == 800.0

    def test_a_new_day_continues_from_the_previous_days_last_record(self, account, project):
        trade("buy", "AAPL", 2, today="2025-10-02")
        write_prices(
            project,
            {
                "AAPL": {"2025-10-01": bar(99, 100), "2025-10-02": bar(100, 101), "2025-10-03": bar(110)},
                "MSFT": {"2025-10-01": bar(199, 200), "2025-10-02": bar(200, 201), "2025-10-03": bar(210)},
            },
        )
        result = trade("sell", "AAPL", 1, today="2025-10-03")
        assert result == {"CASH": 800.0 + 110.0, "AAPL": 1, "MSFT": 5}
        last = read_positions(account)[-1]
        assert (last["date"], last["id"]) == ("2025-10-03", 2)  # the id continues from yesterday's last record (1)

    @pytest.mark.parametrize("action", ["buy", "sell"])
    @pytest.mark.parametrize("amount", [0, -1, -50, 1.5, "3", None, True])
    def test_a_bad_amount_changes_nothing(self, account, action, amount):
        before = (account / "position" / "position.jsonl").read_text()
        result = trade(action, "AAPL" if action == "buy" else "MSFT", amount)
        assert "error" in result and result["symbol"] and result["date"] == "2025-10-02"
        assert (account / "position" / "position.jsonl").read_text() == before

    def test_a_negative_buy_does_not_print_money(self, account):
        # the old tool accepted this: cash went UP and the shares went negative
        result = trade("buy", "AAPL", -100)
        assert "error" in result
        assert read_positions(account)[-1]["positions"]["CASH"] == 1000.0

    def test_a_negative_sell_does_not_buy_without_paying(self, account):
        result = trade("sell", "MSFT", -100)
        assert "error" in result
        assert read_positions(account)[-1]["positions"] == {"CASH": 1000.0, "AAPL": 0, "MSFT": 5}

    def test_not_enough_cash(self, account):
        result = trade("buy", "AAPL", 11)
        assert result["error"].startswith("Insufficient cash")
        assert result["required_cash"] == 1100.0 and result["cash_available"] == 1000.0
        assert len(read_positions(account)) == 1

    def test_not_enough_shares(self, account):
        result = trade("sell", "MSFT", 6)
        assert result["error"].startswith("Insufficient shares") and result["have"] == 5
        assert len(read_positions(account)) == 1

    def test_an_unknown_symbol(self, account):
        for action in ("buy", "sell"):
            result = trade(action, "ZZZZ", 1)
            assert result["error"] == "Symbol ZZZZ not found! This action will not be allowed."
            assert result["symbol"] == "ZZZZ" and result["date"] == "2025-10-02"
        assert len(read_positions(account)) == 1

    def test_a_symbol_with_prices_but_no_position_cannot_be_bought_or_sold(self, account):
        assert "Symbol NODATA not found" in trade("buy", "NODATA", 1)["error"]
        assert "error" in trade("sell", "NODATA", 1)

    def test_a_symbol_with_no_opening_price_that_day_is_refused(self, account):
        write_positions(account, [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 1000.0, "NODATA": 0}}])
        result = trade("buy", "NODATA", 1)
        assert "Price is not available" in result["error"]
        assert len(read_positions(account)) == 1

    def test_no_prices_on_the_day_means_no_trade(self, account):
        result = trade("buy", "AAPL", 1, today="2025-10-04")
        assert "error" in result  # a market holiday: no bar, so no price

    def test_an_agent_without_a_position_cannot_trade(self, project, agent, settings):
        write_prices(project, {"AAPL": {"2025-10-02": bar(100)}})
        result = trade("buy", "AAPL", 1)
        assert result["error"] == "No account position found for this date. This action will not be allowed."

    def test_a_position_without_cash_is_refused(self, project, agent):
        write_positions(agent, [{"date": "2025-10-02", "id": 0, "positions": {"AAPL": 1}}])
        write_prices(project, {"AAPL": {"2025-10-02": bar(100)}})
        assert "No account position" in trade("buy", "AAPL", 1)["error"]

    def test_a_custom_price_file(self, account, tmp_path):
        other = tmp_path / "other.jsonl"
        other.write_text(json.dumps({"Meta Data": {"2. Symbol": "AAPL"}, "Time Series (Daily)": {"2025-10-02": bar(10)}}) + "\n")
        assert trade("buy", "AAPL", 10, merged_path=str(other))["CASH"] == 900.0

    def test_an_unsafe_signature_is_refused_before_anything_is_touched(self, account):
        with pytest.raises(ValueError):
            execute_trade("buy", "AAPL", 1, signature="../evil", today_date="2025-10-02")

    def test_a_bad_amount_is_refused_before_anything_is_created(self, account, project):
        result = execute_trade("buy", "ZZZZ", -1, signature="fresh", today_date="2025-10-02")
        assert "Invalid amount" in result["error"]  # the amount is judged before the symbol or the account
        assert not (project / "agent_data" / "fresh").exists()

    def test_the_error_payload_always_names_the_symbol_and_the_date(self, account):
        result = trade("buy", "AAPL", 0)
        assert result["symbol"] == "AAPL" and result["date"] == "2025-10-02"


@pytest.fixture()
def slow_price_lookup(monkeypatch):
    """Make the gap between reading the position and writing the new one wide, so an order that is not under the lock is caught every time."""
    original = trading.get_open_prices

    def slow(*args, **kwargs):
        import time

        time.sleep(0.01)
        return original(*args, **kwargs)

    monkeypatch.setattr(trading, "get_open_prices", slow)


@pytest.mark.usefixtures("slow_price_lookup")
class TestConcurrency:
    def test_parallel_buys_never_spend_money_twice(self, account):
        # 12 threads each try to buy one share at 100 with 1000 in cash: exactly 10 may succeed
        results: list[dict] = []
        gate = threading.Barrier(12)

        def worker():
            gate.wait()
            results.append(trade("buy", "AAPL", 1))

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert sum("error" not in r for r in results) == 10
        records = read_positions(account)
        assert [r["id"] for r in records] == list(range(11))
        assert records[-1]["positions"] == {"CASH": 0.0, "AAPL": 10, "MSFT": 5}

    def test_parallel_buys_and_sells_keep_the_account_consistent(self, account):
        gate = threading.Barrier(10)

        def worker(i):
            gate.wait()
            trade("sell" if i % 2 else "buy", "MSFT" if i % 2 else "AAPL", 1)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        final = read_positions(account)[-1]["positions"]
        assert final == {"CASH": 1000.0 - 5 * 100 + 5 * 200, "AAPL": 5, "MSFT": 0}


def test_the_largest_order_is_far_below_float_trouble():
    assert trading.MAX_AMOUNT == 1_000_000_000
