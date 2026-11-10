import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.constants import NASDAQ_100_SYMBOLS  # noqa: E402


def normalise(data: dict) -> dict:
    """Rename the open and close the way the tools read them ("1. open" -> "1. buy price", "4. close" -> "4. sell price"), and keep only the opening
    price of the latest bar: the latest bar is the one still being traded, so its high, low, close and volume must not be visible."""
    series = next((v for k, v in data.items() if k.startswith("Time Series")), None)
    if not isinstance(series, dict) or not series:
        return data
    for bar in series.values():
        if isinstance(bar, dict):
            if "1. open" in bar:
                bar["1. buy price"] = bar.pop("1. open")
            if "4. close" in bar:
                bar["4. sell price"] = bar.pop("4. close")
    latest = max(series)
    latest_bar = series.get(latest)
    if isinstance(latest_bar, dict):
        buy = latest_bar.get("1. buy price")
        series[latest] = {"1. buy price": buy} if buy is not None else {}
    meta = data.get("Meta Data")
    if isinstance(meta, dict):
        meta["1. Information"] = "Daily Prices (buy price, high, low, sell price) and Volumes"
    return data


def symbol_of(path: str) -> str | None:
    """The NASDAQ 100 symbol a file `daily_prices_<SYMBOL>.json` is for, or None (including for QQQ, which is not a member)."""
    stem = os.path.basename(path)
    if not (stem.startswith("daily_prices_") and stem.endswith(".json")):
        return None
    symbol = stem[len("daily_prices_") : -len(".json")]
    return symbol if symbol in NASDAQ_100_SYMBOLS else None


def merge(data_dir: str) -> int:
    """Write data_dir/merged.jsonl: one line per NASDAQ 100 `daily_prices_<SYMBOL>.json` file, normalised. Returns how many lines were written."""
    written = 0
    with open(os.path.join(data_dir, "merged.jsonl"), "w", encoding="utf-8") as out:
        for path in sorted(glob.glob(os.path.join(data_dir, "daily_price*.json"))):
            if symbol_of(path) is None:
                continue
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                out.write(json.dumps(normalise(data), ensure_ascii=False) + "\n")
                written += 1
    return written


if __name__ == "__main__":
    print(f"{merge(os.path.dirname(os.path.abspath(__file__)))} symbols merged")
