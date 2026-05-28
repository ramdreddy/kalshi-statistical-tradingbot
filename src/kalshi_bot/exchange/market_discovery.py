"""Discover open Kalshi weather bracket markets via the REST API."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from kalshi_bot.config import Settings
from kalshi_bot.domain.market import BracketStrikeType, WeatherBracketMarket
from kalshi_bot.exchange.kalshi_rest import kalshi_get_json
from kalshi_bot.feeds.weather_locations import (
    KNOWN_DAILY_HIGH_SERIES,
    dedupe_series_by_city,
    is_discoverable_daily_high_series,
    series_ticker_from_market_ticker,
)

logger = logging.getLogger(__name__)

_BRACKET_TITLE_RE = re.compile(
    r"(\d+)\s*°?\s*(?:to|-|–)\s*(\d+)\s*°?",
    re.IGNORECASE,
)
_BELOW_TITLE_RE = re.compile(r"(\d+)\s*°?\s*or\s+below", re.IGNORECASE)
_ABOVE_TITLE_RE = re.compile(r"(\d+)\s*°?\s*or\s+above", re.IGNORECASE)
_LESS_THAN_TITLE_RE = re.compile(r"<\s*(\d+)", re.IGNORECASE)
_TICKER_BRACKET_RE = re.compile(r"-B(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?", re.IGNORECASE)


def _parse_ts(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _volume_score(market: dict[str, Any]) -> float:
    for key in ("volume_24h_fp", "volume_fp", "volume"):
        raw = market.get(key)
        if raw is None:
            continue
        try:
            return float(str(raw).replace(",", ""))
        except ValueError:
            continue
    return 0.0


def _parse_strike_type(raw: Any) -> BracketStrikeType | None:
    if not raw:
        return None
    try:
        return BracketStrikeType(str(raw).lower())
    except ValueError:
        return None


def _parse_from_title(title: str, subtitle: str) -> tuple[BracketStrikeType, float | None, float | None] | None:
    text = f"{title} {subtitle}".strip()
    match = _BRACKET_TITLE_RE.search(text)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        return BracketStrikeType.BETWEEN, low, high
    match = _BELOW_TITLE_RE.search(text)
    if match:
        return BracketStrikeType.LESS_OR_EQUAL, None, float(match.group(1))
    match = _ABOVE_TITLE_RE.search(text)
    if match:
        return BracketStrikeType.GREATER_OR_EQUAL, float(match.group(1)), None
    return None


def _parse_from_ticker(ticker: str) -> tuple[BracketStrikeType, float | None, float | None] | None:
    match = _TICKER_BRACKET_RE.search(ticker.upper())
    if not match:
        return None
    low = float(match.group(1))
    if match.group(2):
        high = float(match.group(2))
        return BracketStrikeType.BETWEEN, low, high
    return BracketStrikeType.BETWEEN, low, low + 1.0


def _series_ticker_from_raw(raw: dict[str, Any], market_ticker: str) -> str:
    series = str(raw.get("series_ticker") or "").upper()
    if series:
        return series
    event = str(raw.get("event_ticker") or "").upper()
    if event:
        return event.split("-", 1)[0]
    return series_ticker_from_market_ticker(market_ticker)


def parse_weather_market(raw: dict[str, Any]) -> WeatherBracketMarket | None:
    """Build a ``WeatherBracketMarket`` from a Kalshi ``/markets`` record."""
    ticker = str(raw.get("ticker") or "").upper()
    if not ticker:
        return None

    event_ticker = str(raw.get("event_ticker") or "").upper()
    series_ticker = _series_ticker_from_raw(raw, ticker)
    title = str(raw.get("title") or raw.get("yes_sub_title") or "")
    subtitle = str(raw.get("subtitle") or raw.get("no_sub_title") or "")

    strike_type = _parse_strike_type(raw.get("strike_type"))
    floor_f = raw.get("floor_strike")
    cap_f = raw.get("cap_strike")
    floor = float(floor_f) if floor_f is not None else None
    cap = float(cap_f) if cap_f is not None else None

    if strike_type is None or (floor is None and cap is None):
        parsed = _parse_from_title(title, subtitle) or _parse_from_ticker(ticker)
        if parsed:
            strike_type, floor, cap = parsed

    if strike_type is None:
        if floor is not None and cap is not None:
            strike_type = BracketStrikeType.BETWEEN
        elif floor is not None:
            strike_type = BracketStrikeType.GREATER_OR_EQUAL
        elif cap is not None:
            strike_type = BracketStrikeType.LESS_OR_EQUAL
        else:
            threshold = _legacy_threshold_from_ticker(ticker)
            if threshold is None:
                return None
            text = f"{title} {subtitle}"
            less_match = _LESS_THAN_TITLE_RE.search(text)
            if less_match or "be <" in text.lower():
                strike_type = BracketStrikeType.LESS_OR_EQUAL
                cap = float(less_match.group(1)) - 1 if less_match else threshold - 1
            else:
                strike_type = BracketStrikeType.GREATER_OR_EQUAL
                floor = threshold

    if strike_type == BracketStrikeType.BETWEEN and floor is not None and cap is None:
        cap = floor + 1.0

    return WeatherBracketMarket(
        ticker=ticker,
        event_ticker=event_ticker,
        series_ticker=series_ticker,
        title=title or subtitle or ticker,
        strike_type=strike_type,
        floor_f=floor,
        cap_f=cap,
        subtitle=subtitle,
    )


def _legacy_threshold_from_ticker(ticker: str) -> float | None:
    """Parse ``KXHIGHNY-26MAY24-T75`` style threshold tickers."""
    upper = ticker.upper()
    if "-T" not in upper:
        return None
    suffix = upper.rsplit("-T", 1)[-1]
    try:
        return float(suffix)
    except ValueError:
        return None


async def fetch_series_page(
    settings: Settings,
    *,
    cursor: str | None = None,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, str | int] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    payload = await kalshi_get_json(settings, "/series", params=params)
    series = list(payload.get("series") or [])
    next_cursor = payload.get("cursor") or None
    return series, next_cursor if next_cursor else None


async def fetch_all_series(settings: Settings) -> list[dict[str, Any]]:
    all_series: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page, cursor = await fetch_series_page(settings, cursor=cursor)
        all_series.extend(page)
        if not cursor:
            break
    return all_series


def _cap_series_list(settings: Settings, series_list: list[str]) -> list[str]:
    deduped = dedupe_series_by_city(series_list)
    max_series = max(1, settings.weather_max_series)
    if len(deduped) <= max_series:
        return deduped
    logger.info(
        "capping weather series %d -> %d (set WEATHER_MAX_SERIES to change)",
        len(deduped),
        max_series,
    )
    return deduped[:max_series]


async def resolve_weather_series_tickers(settings: Settings) -> list[str]:
    """
    Series to scan for open brackets.

    - ``single``: only ``WEATHER_SERIES_TICKER`` (default NYC high).
    - ``all``: daily **high** temp cities only (KXHIGHT*/KXHIGH*), deduped per city.
    """
    if settings.weather_discovery_scope.lower() == "single":
        return [settings.weather_series_ticker.upper()]

    if settings.weather_series_tickers.strip():
        explicit = [
            part.strip().upper()
            for part in settings.weather_series_tickers.split(",")
            if part.strip()
        ]
        return _cap_series_list(settings, explicit)

    discovered: list[str] = []
    try:
        for row in await fetch_all_series(settings):
            ticker = str(row.get("ticker") or "").upper()
            if ticker and is_discoverable_daily_high_series(ticker):
                discovered.append(ticker)
    except Exception:
        logger.warning("could not list /series; using known daily-high series list", exc_info=True)

    if discovered:
        return _cap_series_list(settings, discovered)

    return _cap_series_list(settings, list(KNOWN_DAILY_HIGH_SERIES))


def cap_discovered_markets(
    settings: Settings,
    brackets: list[WeatherBracketMarket],
) -> list[WeatherBracketMarket]:
    """Limit total markets for WebSocket subscriptions and strategy load."""
    max_markets = max(1, settings.weather_max_markets)
    if len(brackets) <= max_markets:
        return brackets
    logger.info(
        "capping discovered markets %d -> %d (set WEATHER_MAX_MARKETS to change)",
        len(brackets),
        max_markets,
    )
    by_series: dict[str, list[WeatherBracketMarket]] = defaultdict(list)
    for bracket in brackets:
        by_series[bracket.series_ticker].append(bracket)

    per_series = max(1, max_markets // max(1, len(by_series)))
    capped: list[WeatherBracketMarket] = []
    for series in sorted(by_series.keys()):
        capped.extend(by_series[series][:per_series])
    return capped[:max_markets]


async def fetch_markets_page(
    settings: Settings,
    *,
    series_ticker: str,
    status: str = "open",
    event_ticker: str | None = None,
    cursor: str | None = None,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, str | int] = {
        "series_ticker": series_ticker.upper(),
        "status": status,
        "limit": limit,
    }
    if event_ticker:
        params["event_ticker"] = event_ticker.upper()
    if cursor:
        params["cursor"] = cursor

    payload = await kalshi_get_json(settings, "/markets", params=params)
    markets = list(payload.get("markets") or [])
    next_cursor = payload.get("cursor") or None
    return markets, next_cursor if next_cursor else None


async def fetch_all_open_markets(
    settings: Settings,
    *,
    series_ticker: str,
    event_ticker: str | None = None,
) -> list[dict[str, Any]]:
    all_markets: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        page, cursor = await fetch_markets_page(
            settings,
            series_ticker=series_ticker,
            event_ticker=event_ticker,
            cursor=cursor,
        )
        all_markets.extend(page)
        if not cursor:
            break
    return all_markets


def _select_primary_event(
    markets: list[dict[str, Any]],
    *,
    preferred_event_ticker: str | None = None,
) -> str | None:
    if preferred_event_ticker:
        target = preferred_event_ticker.upper()
        if any(str(m.get("event_ticker", "")).upper() == target for m in markets):
            return target

    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for market in markets:
        event = str(market.get("event_ticker") or "").upper()
        if event:
            by_event[event].append(market)

    if not by_event:
        return None

    def event_score(event: str) -> tuple[float, float, int]:
        group = by_event[event]
        close_times = [_parse_ts(m.get("close_time")) for m in group]
        close_times = [t for t in close_times if t is not None]
        latest_close = max(close_times).timestamp() if close_times else 0.0
        total_volume = sum(_volume_score(m) for m in group)
        return (latest_close, total_volume, len(group))

    return max(by_event.keys(), key=event_score)


async def discover_brackets_for_series(
    settings: Settings,
    series_ticker: str,
) -> list[WeatherBracketMarket]:
    """Open brackets for the primary event in one weather series (e.g. KXHIGHCHI)."""
    series = series_ticker.upper()
    raw_markets = await fetch_all_open_markets(
        settings,
        series_ticker=series,
        event_ticker=settings.weather_event_ticker or None,
    )

    if settings.weather_event_ticker:
        event = settings.weather_event_ticker.upper()
    else:
        event = _select_primary_event(raw_markets)

    if not event:
        logger.debug("no open event for series=%s", series)
        return []

    brackets: list[WeatherBracketMarket] = []
    for raw in raw_markets:
        if str(raw.get("event_ticker") or "").upper() != event:
            continue
        parsed = parse_weather_market(raw)
        if parsed is not None:
            brackets.append(parsed)

    brackets.sort(key=lambda m: (m.floor_f or -999.0, m.cap_f or 999.0))
    if brackets:
        logger.info(
            "discovered %d bracket(s) for event=%s series=%s",
            len(brackets),
            event,
            series,
        )
    return brackets


async def discover_weather_brackets(settings: Settings) -> list[WeatherBracketMarket]:
    """
    Discover open weather brackets across one or all configured series.

    When ``weather_discovery_scope`` is ``all``, scans every Kalshi weather
    series (KXHIGH*, KXLOW*, etc.) and returns brackets for each city's
    current event.
    """
    series_list = await resolve_weather_series_tickers(settings)
    logger.info(
        "market discovery scope=%s scanning %d series: %s",
        settings.weather_discovery_scope,
        len(series_list),
        ", ".join(series_list[:12]) + ("..." if len(series_list) > 12 else ""),
    )

    all_brackets: list[WeatherBracketMarket] = []
    for series in series_list:
        try:
            brackets = await discover_brackets_for_series(settings, series)
            all_brackets.extend(brackets)
        except Exception:
            logger.warning("discovery failed for series=%s", series, exc_info=True)

    capped = cap_discovered_markets(settings, all_brackets)
    for bracket in capped:
        logger.info(
            "  %s | %s | %s",
            bracket.series_ticker,
            bracket.ticker,
            bracket.describe_bracket(),
        )
    return capped


def manual_fallback_market(settings: Settings) -> WeatherBracketMarket:
    """Single-market mode using ``WEATHER_STRIKE_TEMP_F`` from config."""
    ticker = settings.kalshi_market_ticker.upper()
    series = settings.weather_series_ticker.upper()
    if not series:
        series = series_ticker_from_market_ticker(ticker)
    threshold = settings.weather_strike_temp_f
    legacy = _legacy_threshold_from_ticker(ticker)
    if legacy is not None:
        threshold = legacy
    return WeatherBracketMarket(
        ticker=ticker,
        event_ticker=ticker.rsplit("-", 1)[0] if "-" in ticker else ticker,
        series_ticker=series,
        title=f">= {threshold:.0f}°F (manual)",
        strike_type=BracketStrikeType.GREATER_OR_EQUAL,
        floor_f=threshold,
    )


async def resolve_trading_markets(settings: Settings) -> list[WeatherBracketMarket]:
    """
    Return markets to trade: auto-discovered brackets or a manual fallback ticker.
    """
    if not settings.auto_discover_markets:
        return [manual_fallback_market(settings)]

    if settings.use_mock_exchange:
        return _mock_discovered_brackets(settings)

    brackets = await discover_weather_brackets(settings)
    if brackets:
        return brackets

    logger.warning(
        "auto-discovery found no open brackets (scope=%s); "
        "falling back to KALSHI_MARKET_TICKER=%s",
        settings.weather_discovery_scope,
        settings.kalshi_market_ticker,
    )
    return [manual_fallback_market(settings)]


def _mock_discovered_brackets(settings: Settings) -> list[WeatherBracketMarket]:
    """Synthetic brackets for local mock exchange runs."""
    base = settings.kalshi_market_ticker.upper().split("-")[0]
    strike = settings.weather_strike_temp_f
    low = int(strike) - 1
    high = int(strike) + 1
    return [
        WeatherBracketMarket(
            ticker=f"{base}-MOCK-B{low}-{high}",
            event_ticker=f"{base}-MOCK",
            series_ticker=base,
            title=f"{low}° to {high}°",
            strike_type=BracketStrikeType.BETWEEN,
            floor_f=float(low),
            cap_f=float(high),
        ),
        WeatherBracketMarket(
            ticker=settings.kalshi_market_ticker.upper(),
            event_ticker=f"{base}-MOCK",
            series_ticker=base,
            title=f">= {strike:.0f}°F",
            strike_type=BracketStrikeType.GREATER_OR_EQUAL,
            floor_f=strike,
        ),
    ]
