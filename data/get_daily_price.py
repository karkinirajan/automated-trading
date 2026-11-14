import json

from alphavantage import DATA_DIR, fetch_series

from tools.constants import NASDAQ_100_SYMBOLS


def get_daily_price(SYMBOL: str) -> bool:
    """Download the daily series of one symbol into data/daily_prices_<SYMBOL>.json (QQQ is also saved as Adaily_prices_QQQ.json). False if it failed."""
    data = fetch_series(function="TIME_SERIES_DAILY", symbol=SYMBOL, outputsize="compact")
    if data is None:
        return False
    names = [f"daily_prices_{SYMBOL}.json"] + ([f"Adaily_prices_{SYMBOL}.json"] if SYMBOL == "QQQ" else [])
    for name in names:
        (DATA_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
    return True


if __name__ == "__main__":
    results = [get_daily_price(symbol) for symbol in [*NASDAQ_100_SYMBOLS, "QQQ"]]
    print(f"{sum(results)} of {len(results)} symbols downloaded")
