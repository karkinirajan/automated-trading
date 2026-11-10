import pytest

from tools.price_access import BLOCKED, FULL, OPEN_ONLY, lookup, ohlcv, parse_moment, visibility

BAR = {"1. buy price": "10", "2. high": "12", "3. low": "9", "4. sell price": "11", "5. volume": "500"}
SERIES = {"2025-10-01": BAR, "2025-10-02": BAR, "2025-10-03": BAR, "2025-10-06": BAR}


class TestParseMoment:
    def test_a_date_and_a_time(self):
        assert parse_moment("2025-10-02").isoformat() == "2025-10-02T00:00:00"
        assert parse_moment("2025-10-02 15:30:00").isoformat() == "2025-10-02T15:30:00"

    @pytest.mark.parametrize("value", ["", "2025-10", "10/02/2025", "2025-10-02T15:30:00", "2025-13-01", "2025-10-02 25:00:00", None, 5, "tomorrow"])
    def test_anything_else_is_none(self, value):
        assert parse_moment(value) is None


class TestVisibilityDaily:
    def test_the_past_is_fully_visible(self):
        assert visibility("2025-10-01", "2025-10-02", hourly=False) == FULL

    def test_today_shows_only_the_open(self):
        assert visibility("2025-10-02", "2025-10-02", hourly=False) == OPEN_ONLY

    def test_the_future_is_blocked(self):
        assert visibility("2025-10-03", "2025-10-02", hourly=False) == BLOCKED
        assert visibility("2026-01-01", "2025-10-02", hourly=False) == BLOCKED

    def test_a_daily_price_for_the_current_day_is_open_only_even_when_today_has_an_hour(self):
        # in an hourly run the day is not over: its full OHLCV would include hours that have not happened yet
        assert visibility("2025-10-02", "2025-10-02 10:00:00", hourly=False) == OPEN_ONLY
        assert visibility("2025-10-01", "2025-10-02 10:00:00", hourly=False) == FULL
        assert visibility("2025-10-03", "2025-10-02 10:00:00", hourly=False) == BLOCKED


class TestVisibilityHourly:
    def test_an_earlier_hour_is_visible(self):
        assert visibility("2025-10-02 10:00:00", "2025-10-02 11:00:00", hourly=True) == FULL
        assert visibility("2025-10-01 15:00:00", "2025-10-02 10:00:00", hourly=True) == FULL

    def test_this_hour_shows_only_the_open(self):
        assert visibility("2025-10-02 11:00:00", "2025-10-02 11:00:00", hourly=True) == OPEN_ONLY

    def test_a_later_hour_is_blocked(self):
        assert visibility("2025-10-02 12:00:00", "2025-10-02 11:00:00", hourly=True) == BLOCKED
        assert visibility("2025-10-03 09:00:00", "2025-10-02 11:00:00", hourly=True) == BLOCKED

    def test_one_second_after_is_blocked(self):
        assert visibility("2025-10-02 11:00:01", "2025-10-02 11:00:00", hourly=True) == BLOCKED


class TestVisibilityWithoutAClock:
    @pytest.mark.parametrize("today", [None, "", "garbage", "2025-13-45"])
    def test_everything_is_blocked(self, today):
        assert visibility("2025-10-01", today, hourly=False) == BLOCKED
        assert visibility("2025-10-01 10:00:00", today, hourly=True) == BLOCKED

    def test_an_unreadable_query_is_blocked(self):
        assert visibility("garbage", "2025-10-02", hourly=False) == BLOCKED


class TestOhlcv:
    def test_a_full_bar(self):
        assert ohlcv(BAR, FULL) == {"open": "10", "high": "12", "low": "9", "close": "11", "volume": "500"}

    def test_an_open_only_bar_hides_everything_but_the_open(self):
        out = ohlcv(BAR, OPEN_ONLY)
        assert out["open"] == "10"
        assert out["high"] == "You can not get the current high price"
        assert out["low"] == "You can not get the current low price"
        assert out["close"] == "You can not get the next close price"
        assert out["volume"] == "You can not get the current volume"
        assert "12" not in out.values() and "11" not in out.values() and "500" not in out.values()

    def test_missing_fields_are_none(self):
        assert ohlcv({}, FULL) == {"open": None, "high": None, "low": None, "close": None, "volume": None}


class TestLookup:
    def test_a_past_day(self):
        out = lookup(SERIES, "AAPL", "2025-10-01", "2025-10-02", hourly=False)
        assert out == {"symbol": "AAPL", "date": "2025-10-01", "ohlcv": ohlcv(BAR, FULL)}

    def test_today_is_masked(self):
        out = lookup(SERIES, "AAPL", "2025-10-02", "2025-10-02", hourly=False)
        assert out["ohlcv"] == ohlcv(BAR, OPEN_ONLY)

    def test_tomorrow_is_refused_even_though_the_data_exists(self):
        out = lookup(SERIES, "AAPL", "2025-10-03", "2025-10-02", hourly=False)
        assert out == {"error": "Data for dates after the current time is not available.", "symbol": "AAPL", "date": "2025-10-03"}
        assert "ohlcv" not in out

    def test_without_a_clock_nothing_is_served(self):
        out = lookup(SERIES, "AAPL", "2025-10-01", None, hourly=False)
        assert "TODAY_DATE is not set" in out["error"] and "ohlcv" not in out

    def test_a_missing_day_lists_only_days_that_are_not_in_the_future(self):
        out = lookup(SERIES, "AAPL", "2025-09-30", "2025-10-02", hourly=False)
        assert out["error"].endswith("Sample available dates: ['2025-10-02', '2025-10-01']")
        assert "2025-10-06" not in out["error"] and "2025-10-03" not in out["error"]

    def test_the_sample_is_at_most_five_newest_first(self):
        series = {f"2025-09-{d:02d}": BAR for d in range(1, 21)}
        out = lookup(series, "A", "2025-08-01", "2025-09-30", hourly=False)
        assert out["error"].endswith("['2025-09-20', '2025-09-19', '2025-09-18', '2025-09-17', '2025-09-16']")

    def test_a_bar_that_is_not_a_mapping_counts_as_missing(self):
        assert "Data not found" in lookup({"2025-10-01": "oops"}, "A", "2025-10-01", "2025-10-02", hourly=False)["error"]

    def test_hourly(self):
        series = {"2025-10-02 10:00:00": BAR, "2025-10-02 11:00:00": BAR, "2025-10-02 12:00:00": BAR}
        assert lookup(series, "A", "2025-10-02 10:00:00", "2025-10-02 11:00:00", hourly=True)["ohlcv"] == ohlcv(BAR, FULL)
        assert lookup(series, "A", "2025-10-02 11:00:00", "2025-10-02 11:00:00", hourly=True)["ohlcv"] == ohlcv(BAR, OPEN_ONLY)
        assert "error" in lookup(series, "A", "2025-10-02 12:00:00", "2025-10-02 11:00:00", hourly=True)

    def test_an_hourly_run_does_not_reveal_the_rest_of_todays_daily_bar(self):
        out = lookup({"2025-10-02": BAR}, "A", "2025-10-02", "2025-10-02 10:00:00", hourly=False)
        assert out["ohlcv"] == ohlcv(BAR, OPEN_ONLY)
