"""Fetching one Alpha Vantage time series, shared by the daily and the hourly price scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

URL = "https://www.alphavantage.co/query"
TIMEOUT = (5, 60)  # (connect, read) seconds
DATA_DIR = Path(__file__).resolve().parent  # files are written next to the scripts, whatever the working directory is


def fetch_series(**params: str) -> dict[str, Any] | None:
    """Ask Alpha Vantage (`function`, `symbol`, ... as keyword arguments; the API key comes from ALPHAADVANTAGE_API_KEY).

    Returns the response, or None when the service refused (rate limit, bad key, unknown symbol) or could not be reached; the reason is printed, the key is not.
    """
    key = os.getenv("ALPHAADVANTAGE_API_KEY")
    if not key:
        raise RuntimeError("ALPHAADVANTAGE_API_KEY is not set")
    try:
        response = requests.get(URL, params={**params, "apikey": key}, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        # the exception text can contain the request URL, and so the key: print only what kind of failure it was
        print(f"Alpha Vantage request for {params.get('symbol')} failed: {type(exc).__name__}")
        return None
    if not isinstance(data, dict) or any(k in data for k in ("Note", "Information", "Error Message")):
        reason = next((data[k] for k in ("Note", "Information", "Error Message") if isinstance(data, dict) and k in data), "unexpected response")
        print(f"Alpha Vantage refused {params.get('symbol')}: {str(reason)[:200]}")
        return None
    return data
