"""Run several weather feeds as one (e.g. NWS + The Weather Company)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from kalshi_bot.domain.models import WeatherMetrics
from kalshi_bot.feeds.weather import WeatherFeeder

logger = logging.getLogger(__name__)


class CompositeWeatherFeeder(WeatherFeeder):
    """Merge child feeds; each metric keeps its own ``source`` (``nws:…``, ``twc:…``)."""

    def __init__(self, feeders: list[WeatherFeeder]) -> None:
        if not feeders:
            raise ValueError("CompositeWeatherFeeder needs at least one feeder")
        super().__init__(location="composite", poll_interval_sec=0)
        self._feeders = feeders

    @property
    def feeders(self) -> list[WeatherFeeder]:
        return list(self._feeders)

    async def warm_up(self) -> list[WeatherMetrics]:
        results: list[WeatherMetrics] = []
        for feeder in self._feeders:
            warm = getattr(feeder, "warm_up", None)
            try:
                results.extend(await warm() if warm else [await feeder.fetch_metrics()])
            except Exception:
                logger.exception("warm-up failed for %s", type(feeder).__name__)
        return results

    async def fetch_metrics(self) -> WeatherMetrics:
        return await self._feeders[0].fetch_metrics()

    async def stream(self) -> AsyncIterator[WeatherMetrics]:
        queue: asyncio.Queue[WeatherMetrics] = asyncio.Queue()

        async def pump(feeder: WeatherFeeder) -> None:
            async for metrics in feeder.stream():
                await queue.put(metrics)

        tasks = [asyncio.create_task(pump(f)) for f in self._feeders]
        try:
            while True:
                yield await queue.get()
        finally:
            for task in tasks:
                task.cancel()
