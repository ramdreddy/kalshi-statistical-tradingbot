"""Kalshi weather series → NWS gridpoint coordinates for settlement-aligned forecasts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

# Legacy series (KXHIGH*) and current daily-high series (KXHIGHT*).
HIGH_TEMP_SERIES_PREFIXES: tuple[str, ...] = ("KXHIGHT", "KXHIGH")

# Substrings that disqualify a series from daily-high discovery.
_EXCLUDED_SERIES_MARKERS: tuple[str, ...] = (
    "INFLATION",
    "RAIN",
    "SNOW",
    "SNW",
    "PRECIP",
    "MOVDJT",
    "MOVKH",
    "TEMPDEN",
)

# Fallback when /series listing is empty.
KNOWN_DAILY_HIGH_SERIES: tuple[str, ...] = (
    "KXHIGHTNYC",
    "KXHIGHTCHI",
    "KXHIGHTMIA",
    "KXHIGHTLAX",
    "KXHIGHTDEN",
    "KXHIGHTAUS",
    "KXHIGHTPHX",
    "KXHIGHTATL",
    "KXHIGHTDAL",
    "KXHIGHTHOU",
    "KXHIGHTSEA",
    "KXHIGHTBOS",
)


@dataclass(frozen=True)
class WeatherLocation:
    latitude: float
    longitude: float
    label: str


# City suffix after KXHIGH(T) — settlement stations / airports used by Kalshi.
CITY_LOCATIONS: dict[str, WeatherLocation] = {
    "NY": WeatherLocation(40.7812, -73.9665, "New York, NY (Central Park)"),
    "NYC": WeatherLocation(40.7812, -73.9665, "New York, NY (Central Park)"),
    "CHI": WeatherLocation(41.9742, -87.9073, "Chicago, IL (O'Hare)"),
    "MIA": WeatherLocation(25.7959, -80.2870, "Miami, FL (MIA)"),
    "LAX": WeatherLocation(33.9425, -118.4081, "Los Angeles, CA (LAX)"),
    "DEN": WeatherLocation(39.8561, -104.6737, "Denver, CO (DEN)"),
    "AUS": WeatherLocation(30.1975, -97.6664, "Austin, TX (AUS)"),
    "PHX": WeatherLocation(33.4342, -112.0116, "Phoenix, AZ (PHX)"),
    "ATL": WeatherLocation(33.6407, -84.4277, "Atlanta, GA (ATL)"),
    "DFW": WeatherLocation(32.8998, -97.0403, "Dallas/Fort Worth, TX (DFW)"),
    "DAL": WeatherLocation(32.8998, -97.0403, "Dallas/Fort Worth, TX (DFW)"),
    "HOU": WeatherLocation(29.9902, -95.3368, "Houston, TX (IAH)"),
    "SEA": WeatherLocation(47.4502, -122.3088, "Seattle, WA (SEA)"),
    "BOS": WeatherLocation(42.3656, -71.0096, "Boston, MA (BOS)"),
    "PHIL": WeatherLocation(39.8744, -75.2424, "Philadelphia, PA (PHL)"),
    "DC": WeatherLocation(38.8512, -77.0402, "Washington, DC (DCA)"),
    "LV": WeatherLocation(36.0840, -115.1537, "Las Vegas, NV (LAS)"),
    "MIN": WeatherLocation(44.8848, -93.2223, "Minneapolis, MN (MSP)"),
    "NOLA": WeatherLocation(29.9934, -90.2580, "New Orleans, LA (MSY)"),
    "OKC": WeatherLocation(35.3931, -97.6007, "Oklahoma City, OK (OKC)"),
    "SATX": WeatherLocation(29.5337, -98.4698, "San Antonio, TX (SAT)"),
    "SFO": WeatherLocation(37.6213, -122.3790, "San Francisco, CA (SFO)"),
}

# IANA timezone for matching NWS forecast periods to Kalshi settlement days.
CITY_TIMEZONES: dict[str, str] = {
    "NYC": "America/New_York",
    "CHI": "America/Chicago",
    "MIA": "America/New_York",
    "LAX": "America/Los_Angeles",
    "DEN": "America/Denver",
    "AUS": "America/Chicago",
    "PHX": "America/Phoenix",
    "ATL": "America/New_York",
    "DFW": "America/Chicago",
    "DAL": "America/Chicago",
    "HOU": "America/Chicago",
    "SEA": "America/Los_Angeles",
    "BOS": "America/New_York",
    "PHIL": "America/New_York",
    "DC": "America/New_York",
    "LV": "America/Los_Angeles",
    "MIN": "America/Chicago",
    "NOLA": "America/Chicago",
    "OKC": "America/Chicago",
    "SATX": "America/Chicago",
    "SFO": "America/Los_Angeles",
}

# Direct series-ticker aliases (older KXHIGH* tickers).
SERIES_ALIASES: dict[str, str] = {
    "KXHIGHNY": "NYC",
    "KXHIGHCHI": "CHI",
    "KXHIGHMIA": "MIA",
    "KXHIGHLAX": "LAX",
    "KXHIGHDEN": "DEN",
    "KXHIGHAUS": "AUS",
    "KXHIGHPHX": "PHX",
    "KXHIGHATL": "ATL",
    "KXHIGHDFW": "DFW",
    "KXHIGHHOU": "HOU",
    "KXHIGHSEA": "SEA",
    "KXHIGHBOS": "BOS",
    "KXHIGHPHIL": "PHIL",
}


def series_ticker_from_market_ticker(market_ticker: str) -> str:
    """``KXHIGHNY-26MAY27-B79`` → ``KXHIGHNY``."""
    return market_ticker.upper().split("-", 1)[0]


def city_key_from_series(series_ticker: str) -> str | None:
    """Map ``KXHIGHTATL`` / ``KXHIGHCHI`` → ``ATL`` / ``CHI``."""
    series = series_ticker.upper()
    if series in SERIES_ALIASES:
        return SERIES_ALIASES[series]
    if series.startswith("KXHIGHT"):
        return series[len("KXHIGHT") :]
    if series.startswith("KXHIGH"):
        suffix = series[len("KXHIGH") :]
        if not suffix or suffix in ("INFLATION",):
            return None
        return suffix
    return None


def is_discoverable_daily_high_series(series_ticker: str) -> bool:
    """Daily maximum temperature brackets only (no rain/low/inflation)."""
    series = series_ticker.upper()
    if any(marker in series for marker in _EXCLUDED_SERIES_MARKERS):
        return False
    if series.startswith("KXLOW"):
        return False
    if not any(series.startswith(prefix) for prefix in HIGH_TEMP_SERIES_PREFIXES):
        return False
    return location_for_series(series) is not None


def is_weather_series_ticker(series_ticker: str) -> bool:
    """Backward-compatible alias used by discovery tests."""
    return is_discoverable_daily_high_series(series_ticker)


def dedupe_series_by_city(series_tickers: list[str]) -> list[str]:
    """
    One series per city. Prefer ``KXHIGHT*`` (current) over legacy ``KXHIGH*``.
    """
    by_city: dict[str, list[str]] = {}
    for series in series_tickers:
        city = city_key_from_series(series)
        if not city:
            continue
        by_city.setdefault(city, []).append(series.upper())

    chosen: list[str] = []
    for city in sorted(by_city.keys()):
        options = by_city[city]
        t_format = sorted(s for s in options if s.startswith("KXHIGHT"))
        if t_format:
            chosen.append(t_format[0])
        else:
            chosen.append(sorted(options)[0])
    return chosen


def location_for_series(series_ticker: str) -> WeatherLocation | None:
    series = series_ticker.upper()
    city = city_key_from_series(series)
    if city and city in CITY_LOCATIONS:
        return CITY_LOCATIONS[city]
    return None


def timezone_for_series(series_ticker: str) -> ZoneInfo:
    """Local timezone for NWS period dates (settlement station city)."""
    city = city_key_from_series(series_ticker)
    if city and city in CITY_TIMEZONES:
        return ZoneInfo(CITY_TIMEZONES[city])
    return ZoneInfo("America/New_York")
