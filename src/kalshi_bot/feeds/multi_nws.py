"""Poll NWS for multiple Kalshi weather series (one forecast per city)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace

from kalshi_bot.config import Settings
from kalshi_bot.domain.market import WeatherBracketMarket
from kalshi_bot.domain.models import WeatherMetrics
from kalshi_bot.feeds.event_dates import event_dates_by_series
from kalshi_bot.feeds.nws import NWSFeeder
from kalshi_bot.feeds.weather import WeatherFeeder
from kalshi_bot.feeds.weather_locations import location_for_series, timezone_for_series

logger = logging.getLogger(__name__)


class MultiSeriesNWSFeeder(WeatherFeeder):
    """Fetch settlement-aligned NWS highs for each discovered weather series."""

    def __init__(
        self,
        feeders: dict[str, NWSFeeder],
        poll_interval_sec: float = 300.0,
    ) -> None:
        super().__init__(location="multi-city NWS", poll_interval_sec=poll_interval_sec)
        self._feeders = feeders

    @classmethod
    def for_markets(
        cls,
        markets: list[WeatherBracketMarket],
        settings: Settings,
    ) -> "MultiSeriesNWSFeeder":
        settlement_dates = event_dates_by_series(markets)
        feeders: dict[str, NWSFeeder] = {}
        for series in sorted(settlement_dates.keys()):
            loc = location_for_series(series)
            if loc is None:
                logger.warning(
                    "no NWS coordinates for series=%s; skipping weather for this city",
                    series,
                )
                continue
            feeders[series] = NWSFeeder(
                latitude=loc.latitude,
                longitude=loc.longitude,
                location=loc.label,
                poll_interval_sec=settings.weather_poll_interval_sec,
                user_agent=settings.nws_user_agent,
                series_ticker=series,
                forecast_date=settlement_dates[series],
                timezone=timezone_for_series(series),
            )
        if not feeders:
            raise ValueError(
                "No weather series have configured NWS locations. "
                "Set WEATHER_DISCOVERY_SCOPE=single or add coordinates in weather_locations.py."
            )
        return cls(feeders, poll_interval_sec=settings.weather_poll_interval_sec)

    @property
    def series_tickers(self) -> list[str]:
        return sorted(self._feeders.keys())

    async def fetch_for_series(self, series: str) -> WeatherMetrics:
        feeder = self._feeders[series.upper()]
        metrics = await feeder.fetch_metrics()
        return replace(
            metrics,
            series_ticker=series.upper(),
            source=f"nws:{series.upper()}",
        )

    async def warm_up(self) -> list[WeatherMetrics]:
        """Fetch NWS for every city before order-book evaluation begins."""
        results: list[WeatherMetrics] = []
        for series in self.series_tickers:
            try:
                results.append(await self.fetch_for_series(series))
            except Exception:
                logger.exception("NWS warm-up failed series=%s", series)
        return results

    async def fetch_metrics(self) -> WeatherMetrics:
        """Return metrics for the first configured series (used by connection tests)."""
        series = self.series_tickers[0]
        return await self.fetch_for_series(series)

    async def stream(self) -> AsyncIterator[WeatherMetrics]:
        while True:
            for series, feeder in self._feeders.items():
                try:
                    metrics = await feeder.fetch_metrics()
                    yield replace(
                        metrics,
                        series_ticker=series,
                        source=f"nws:{series}",
                    )
                except Exception:
                    logger.exception("NWS fetch failed series=%s", series)
            await asyncio.sleep(self._poll_interval_sec)
