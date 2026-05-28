"""Parse Kalshi weather event dates from tickers."""

from __future__ import annotations

import re
from datetime import date

from kalshi_bot.domain.market import WeatherBracketMarket

_KALSHI_EVENT_DATE = re.compile(
    r"^(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})$",
    re.IGNORECASE,
)

_MONTH_TO_NUM: dict[str, int] = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


def parse_event_date_from_ticker(event_ticker: str) -> date | None:
    """
    Parse ``KXHIGHAUS-26MAY28`` → ``date(2026, 5, 28)``.

    Kalshi daily-high events encode the settlement day as ``YYMONDD`` on the
    event ticker suffix (e.g. ``26MAY28``).
    """
    token = event_ticker.upper().rsplit("-", 1)[-1]
    match = _KALSHI_EVENT_DATE.match(token)
    if not match:
        return None
    month = _MONTH_TO_NUM.get(match.group("mon").upper())
    if month is None:
        return None
    year = 2000 + int(match.group("yy"))
    day = int(match.group("dd"))
    try:
        return date(year, month, day)
    except ValueError:
        return None


def event_dates_by_series(markets: list[WeatherBracketMarket]) -> dict[str, date]:
    """Map each series ticker to the settlement date from discovered markets."""
    dates: dict[str, date] = {}
    for market in markets:
        series = market.series_ticker.upper()
        parsed = parse_event_date_from_ticker(market.event_ticker)
        if parsed is None:
            raise ValueError(
                f"Cannot parse settlement date from event_ticker={market.event_ticker!r}"
            )
        existing = dates.get(series)
        if existing is not None and existing != parsed:
            raise ValueError(
                f"Conflicting event dates for series={series}: {existing} vs {parsed}"
            )
        dates[series] = parsed
    return dates
