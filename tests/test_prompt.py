import pytest

from prompts import agent_prompt
from prompts.agent_prompt import STOP_SIGNAL, agent_system_prompt, get_agent_system_prompt
from tests.helpers import bar, write_positions, write_prices


@pytest.fixture()
def world(project, agent):
    write_prices(
        project,
        {
            "AAPL": {"2025-10-01": bar(99, 100), "2025-10-02": bar(101, 105)},
            "MSFT": {"2025-10-01": bar(199, 200), "2025-10-02": bar(None, 205)},
        },
    )
    write_positions(agent, [{"date": "2025-10-01", "id": 0, "positions": {"CASH": 1000.0, "AAPL": 2, "MSFT": 0}}])


class TestPrompt:
    def test_it_fills_in_the_day_the_position_and_the_prices(self, world):
        text = get_agent_system_prompt("2025-10-02", "bot")
        assert "Current time:\n2025-10-02" in text
        assert "{'CASH': 1000.0, 'AAPL': 2, 'MSFT': 0}" in text
        assert "'AAPL_price': 100.0" in text and "'MSFT_price': 200.0" in text  # yesterday's closes
        assert "'AAPL_price': 101.0" in text and "'MSFT_price': None" in text  # today's opens: MSFT has none
        assert text.rstrip().endswith(STOP_SIGNAL)

    def test_it_never_contains_todays_close(self, world):
        text = get_agent_system_prompt("2025-10-02", "bot")
        assert "105" not in text and "205" not in text

    def test_no_placeholder_is_left_unfilled(self, world):
        text = get_agent_system_prompt("2025-10-02", "bot")
        for name in ("{date}", "{positions}", "{yesterday_close_price}", "{today_buy_price}", "{STOP_SIGNAL}"):
            assert name not in text

    def test_the_template_names_exactly_the_fields_the_builder_supplies(self):
        import string

        fields = {name for _, name, _, _ in string.Formatter().parse(agent_system_prompt) if name}
        assert fields == {"date", "positions", "yesterday_close_price", "today_buy_price", "STOP_SIGNAL"}

    def test_an_agent_with_no_history_gets_an_empty_position(self, project):
        write_prices(project, {"AAPL": {"2025-10-01": bar(1, 2)}})
        assert "Your current positions" in get_agent_system_prompt("2025-10-02", "nobody")

    def test_an_unsafe_signature_is_refused(self, world):
        with pytest.raises(ValueError):
            get_agent_system_prompt("2025-10-02", "../x")

    def test_the_symbol_list_is_the_shared_constant(self):
        from tools.constants import NASDAQ_100_SYMBOLS

        assert agent_prompt.all_nasdaq_100_symbols is NASDAQ_100_SYMBOLS
        assert STOP_SIGNAL == "<FINISH_SIGNAL>"
