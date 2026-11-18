"""The Weather Company (weather.com) daily-high forecasts.

Kalshi's daily-high markets resolve on the NWS climate-report station value as
reported by The Weather Company, and the market tends to trade on TWC's own
forecast. Feeding it alongside NWS lets the strategy blend the two and stand
aside when they disagree.

Requires a TWC Data API key (``TWC_API_KEY``); the feed is off without one.
Endpoint: ``/v3/wx/forecast/daily/5day`` (``calendarDayTemperatureMax`` is the
midnight-to-midnight local high, which matches Kalshi's settlement day).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import date
from zoneinfo import ZoneInfo

import httpx

from kalshi_bot.domain.market import WeatherBracketMarket
from kalshi_bot.domain.models import WeatherMetrics
from kalshi_bot.feeds.event_dates import event_dates_by_series
from kalshi_bot.feeds.weather import WeatherFeeder
from kalshi_bot.feeds.weather_locations import location_for_series, timezone_for_series

logger = logging.getLogger(__name__)

TWC_DAILY_URL = "https://api.weather.com/v3/wx/forecast/daily/5day"


def select_twc_daily_high(payload: dict, target: date) -> float | None:
    """Pick ``calendarDayTemperatureMax`` for ``target`` from a 5-day response."""
    times = payload.get("validTimeLocal") or []
    highs = payload.get("calendarDayTemperatureMax") or []
    for stamp, high in zip(times, highs):
        if high is None or not stamp:
            continue
        if date.fromisoformat(str(stamp)[:10]) == target:
            return float(high)
    return None


class TWCFeeder(WeatherFeeder):
    """One city's TWC forecast high for its Kalshi settlement day."""

    def __init__(
        self,
        *,
        latitude: float,
        longitude: float,
        location: str,
        api_key: str,
        series_ticker: str,
        forecast_date: date,
        timezone: ZoneInfo,
        poll_interval_sec: float = 300.0,
    ) -> None:
        super().__init__(location=location, poll_interval_sec=poll_interval_sec)
        self._latitude = latitude
        self._longitude = longitude
        self._api_key = api_key
        self._series_ticker = series_ticker.upper()
        self._forecast_date = forecast_date
        self._timezone = timezone

    async def fetch_metrics(self) -> WeatherMetrics:
        params = {
            "geocode": f"{self._latitude:.4f},{self._longitude:.4f}",
            "format": "json",
            "units": "e",
            "language": "en-US",
            "apiKey": self._api_key,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(TWC_DAILY_URL, params=params)
            response.raise_for_status()
            payload = response.json()
        high = select_twc_daily_high(payload, self._forecast_date)
        if high is None:
            raise ValueError(f"TWC has no forecast for {self._series_ticker} on {self._forecast_date}")
        return WeatherMetrics(
            location=self._location,
            temperature_f=high,
            humidity_pct=0.0,
            wind_speed_mph=0.0,
            forecast_high_f=high,
            source=f"twc:{self._series_ticker}",
            series_ticker=self._series_ticker,
        )


class MultiSeriesTWCFeeder(WeatherFeeder):
    """TWC forecasts for every discovered series that has station coordinates."""

    def __init__(self, feeders: dict[str, TWCFeeder], poll_interval_sec: float = 300.0) -> None:
        super().__init__(location="multi-city TWC", poll_interval_sec=poll_interval_sec)
        self._feeders = feeders

    @classmethod
    def for_markets(
        cls,
        markets: list[WeatherBracketMarket],
        *,
        api_key: str,
        poll_interval_sec: float,
    ) -> "MultiSeriesTWCFeeder":
        feeders: dict[str, TWCFeeder] = {}
        for series, day in sorted(event_dates_by_series(markets).items()):
            loc = location_for_series(series)
            if loc is None:
                continue
            feeders[series] = TWCFeeder(
                latitude=loc.latitude,
                longitude=loc.longitude,
                location=loc.label,
                api_key=api_key,
                series_ticker=series,
                forecast_date=day,
                timezone=timezone_for_series(series),
                poll_interval_sec=poll_interval_sec,
            )
        return cls(feeders, poll_interval_sec=poll_interval_sec)

    @property
    def series_tickers(self) -> list[str]:
        return sorted(self._feeders)

    async def warm_up(self) -> list[WeatherMetrics]:
        results: list[WeatherMetrics] = []
        for series, feeder in self._feeders.items():
            try:
                results.append(await feeder.fetch_metrics())
            except Exception:
                logger.exception("TWC warm-up failed series=%s", series)
        return results

    async def fetch_metrics(self) -> WeatherMetrics:
        return await self._feeders[self.series_tickers[0]].fetch_metrics()

    async def stream(self) -> AsyncIterator[WeatherMetrics]:
        while True:
            for series, feeder in self._feeders.items():
                try:
                    yield await feeder.fetch_metrics()
                except Exception:
                    logger.exception("TWC fetch failed series=%s", series)
            await asyncio.sleep(self._poll_interval_sec)
