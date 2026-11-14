from datetime import datetime

import pytest

from tools.search_filter import allowed_urls, parse_date_to_standard, published_before

NOW = datetime(2026, 11, 10, 12, 0, 0)


class TestParseDate:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2025-10-01T08:19:28+00:00", "2025-10-01 08:19:28"),
            ("2025-10-01T08:19:28Z", "2025-10-01 08:19:28"),
            ("2025-10-01T08:19:28.123456Z", "2025-10-01 08:19:28"),
            ("2025-10-01T08:19:28.5+00:00", "2025-10-01 08:19:28"),
            ("2025-10-01T08:19:28+05:45", "2025-10-01 08:19:28"),
            ("May 31, 2025", "2025-05-31 00:00:00"),
            ("2025-10-01", "2025-10-01 00:00:00"),
        ],
    )
    def test_absolute_dates(self, raw, expected):
        assert parse_date_to_standard(raw, NOW) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("4 hours ago", "2026-11-10 08:00:00"),
            ("1 hour ago", "2026-11-10 11:00:00"),
            ("1 day ago", "2026-11-09 12:00:00"),
            ("3 days ago", "2026-11-07 12:00:00"),
            ("2 weeks ago", "2026-10-27 12:00:00"),
            ("2 months ago", "2026-09-11 12:00:00"),
            ("4 HOURS AGO", "2026-11-10 08:00:00"),
        ],
    )
    def test_relative_dates_are_measured_from_now(self, raw, expected):
        assert parse_date_to_standard(raw, NOW) == expected

    @pytest.mark.parametrize("raw", ["", None, "unknown"])
    def test_nothing_is_unknown(self, raw):
        assert parse_date_to_standard(raw, NOW) == "unknown"

    def test_an_unreadable_date_is_returned_as_it_was(self):
        assert parse_date_to_standard("last Tuesday", NOW) == "last Tuesday"
        assert parse_date_to_standard("31/05/2025", NOW) == "31/05/2025"

    def test_a_relative_date_with_an_unknown_unit_is_unknown(self):
        assert parse_date_to_standard("3 fortnights ago", NOW) == "unknown"

    def test_a_relative_date_without_a_number_is_returned_as_it_was(self):
        assert parse_date_to_standard("long ago", NOW) == "long ago"

    def test_a_malformed_absolute_date_is_returned_as_it_was(self):
        assert parse_date_to_standard("2025-13-45", NOW) == "2025-13-45"
        assert parse_date_to_standard("2025-10-01T99:99:99Z", NOW) == "2025-10-01T99:99:99Z"
        assert parse_date_to_standard("Foo 99, 2025", NOW) == "Foo 99, 2025"

    def test_without_now_it_uses_the_clock(self):
        out = parse_date_to_standard("1 hour ago")
        assert datetime.strptime(out, "%Y-%m-%d %H:%M:%S") < datetime.now()


class TestPublishedBefore:
    def test_everything_may_be_shown_without_a_simulated_date(self):
        assert published_before("2030-01-01", None, NOW) is True
        assert published_before("garbage", "", NOW) is True

    def test_an_earlier_result_may_be_shown(self):
        assert published_before("2025-10-14T23:59:59Z", "2025-10-15", NOW) is True
        assert published_before("2025-10-14", "2025-10-15", NOW) is True

    def test_a_result_from_today_or_later_may_not(self):
        assert published_before("2025-10-15T00:00:00Z", "2025-10-15", NOW) is False  # strictly before: not the moment itself
        assert published_before("2025-10-15T08:00:00Z", "2025-10-15", NOW) is False
        assert published_before("2025-10-16", "2025-10-15", NOW) is False

    def test_a_result_with_no_date_is_dropped(self):
        assert published_before("unknown", "2025-10-15", NOW) is False
        assert published_before("", "2025-10-15", NOW) is False

    def test_a_result_with_an_unreadable_date_is_dropped(self):
        assert published_before("last Tuesday", "2025-10-15", NOW) is False

    def test_relative_dates_are_recent_so_they_are_after_an_old_simulated_date(self):
        assert published_before("4 hours ago", "2025-10-15", NOW) is False

    def test_an_hourly_simulated_moment(self):
        assert published_before("2025-10-15T09:59:59Z", "2025-10-15 10:00:00", NOW) is True
        assert published_before("2025-10-15T10:00:00Z", "2025-10-15 10:00:00", NOW) is False

    def test_an_unreadable_simulated_moment_blocks_everything(self):
        assert published_before("2020-01-01", "garbage", NOW) is False


class TestAllowedUrls:
    ITEMS = [
        {"url": "https://a.example/old", "date": "2025-10-01T00:00:00Z"},
        {"url": "https://b.example/future", "date": "2025-10-20T00:00:00Z"},
        {"url": "https://c.example/undated"},
        {"url": "https://d.example/garbled", "date": "sometime"},
        {"title": "no url", "date": "2025-10-01"},
        {"url": 5, "date": "2025-10-01"},
        "junk",
        None,
        {"url": "https://e.example/also-old", "date": "2025-09-01"},
    ]

    def test_only_readable_earlier_results_with_a_url_are_kept_in_order(self):
        assert allowed_urls(self.ITEMS, "2025-10-15", NOW) == ["https://a.example/old", "https://e.example/also-old"]

    def test_with_no_simulated_date_every_result_with_a_url_is_kept(self):
        assert allowed_urls(self.ITEMS, None, NOW) == [
            "https://a.example/old",
            "https://b.example/future",
            "https://c.example/undated",
            "https://d.example/garbled",
            "https://e.example/also-old",
        ]

    def test_no_results(self):
        assert allowed_urls([], "2025-10-15", NOW) == []
