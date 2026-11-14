import json

from alphavantage import DATA_DIR, fetch_series

from tools.constants import NASDAQ_100_SYMBOLS

SERIES = "Time Series (60min)"


def merge_series(old: dict, new: dict) -> dict:
    """The new download with the older hourly bars kept: a timestamp in both takes the new bar; the old Meta Data is kept if the new one has none."""
    merged = dict(new)
    merged[SERIES] = {**old.get(SERIES, {}), **new.get(SERIES, {})}
    if "Meta Data" not in merged and "Meta Data" in old:
        merged["Meta Data"] = old["Meta Data"]
    return merged


def update_json(data: dict, SYMBOL: str) -> None:
    """Merge a download into data/daily_prices_<SYMBOL>.json (QQQ: also into Adaily_prices_QQQ.json)."""
    names = [f"daily_prices_{SYMBOL}.json"] + ([f"Adaily_prices_{SYMBOL}.json"] if SYMBOL == "QQQ" else [])
    for name in names:
        path = DATA_DIR / name
        merged = merge_series(json.loads(path.read_text(encoding="utf-8")), data) if path.exists() else data
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=4), encoding="utf-8")


def get_daily_price(SYMBOL: str) -> bool:
    """Download the last hourly bars of one symbol and merge them into its file. False if the download failed."""
    data = fetch_series(
        function="TIME_SERIES_INTRADAY",
        symbol=SYMBOL,
        interval="60min",
        outputsize="full",
        entitlement="delayed",
        extended_hours="false",
    )
    if data is None:
        return False
    update_json(data, SYMBOL)
    return True


if __name__ == "__main__":
    results = [get_daily_price(symbol) for symbol in [*NASDAQ_100_SYMBOLS, "QQQ"]]
    print(f"{sum(results)} of {len(results)} symbols downloaded")
