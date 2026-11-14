"""Keeping web search results from the future: a result published at or after the simulated "today" must not reach the agent."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from tools.price_access import parse_moment

STANDARD_FORMAT = "%Y-%m-%d %H:%M:%S"
UNKNOWN = "unknown"
_RELATIVE_UNITS = (("hour", "hours"), ("day", "days"), ("week", "weeks"), ("month", "months"))


def parse_date_to_standard(date_str: str, now: datetime | None = None) -> str:
    """Convert a search result's date to "YYYY-MM-DD HH:MM:SS".

    Understands ISO 8601 ("2025-10-01T08:19:28+00:00"), "May 31, 2025", "2025-10-01" and relative forms ("4 hours ago", "2 weeks ago": measured from the real
    current time, `now`, because the page was published relative to when it was fetched). Returns "unknown" for an empty value and the original text when it cannot
    be read.
    """
    if not date_str or date_str == UNKNOWN:
        return UNKNOWN
    now = now or datetime.now()
    lowered = date_str.lower()

    if "ago" in lowered:
        digits = re.findall(r"\d+", date_str)
        for unit, keyword in _RELATIVE_UNITS:
            if unit in lowered and digits:
                count = int(digits[0])
                delta = timedelta(days=count * 30) if unit == "month" else timedelta(**{keyword if unit != "day" else "days": count})
                return (now - delta).strftime(STANDARD_FORMAT)
        if not digits:
            return date_str
        return UNKNOWN

    if "T" in date_str and ("+" in date_str or "Z" in date_str or date_str.endswith("00:00")):
        core = date_str.split("+")[0] if "+" in date_str else date_str.replace("Z", "")
        try:
            return datetime.strptime(core.split(".")[0], "%Y-%m-%dT%H:%M:%S").strftime(STANDARD_FORMAT)
        except ValueError:
            pass

    if "," in date_str and len(date_str.split()) >= 3:
        try:
            return datetime.strptime(date_str, "%b %d, %Y").strftime(STANDARD_FORMAT)
        except ValueError:
            pass

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").strftime(STANDARD_FORMAT)
        except ValueError:
            pass

    return date_str


def published_before(raw_date: str, today: str | None, now: datetime | None = None) -> bool:
    """Whether a result dated `raw_date` may be shown while the simulated moment is `today`.

    With no `today`, everything may. With one, only a result whose date can be read AND is strictly earlier than `today` may: a result with no date, or one
    that cannot be read, is dropped (it used to be kept, which let undated pages from after the simulated date through).
    """
    if not today:
        return True
    limit = parse_moment(today)
    if limit is None:
        return False
    standard = parse_date_to_standard(raw_date, now)
    try:
        published = datetime.strptime(standard, STANDARD_FORMAT)
    except ValueError:
        return False
    return published < limit


def allowed_urls(items: list[Any], today: str | None, now: datetime | None = None) -> list[str]:
    """The URLs of the search results that may be shown, in order."""
    urls: list[str] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("url"), str) and published_before(item.get("date", UNKNOWN), today, now):
            urls.append(item["url"])
    return urls
