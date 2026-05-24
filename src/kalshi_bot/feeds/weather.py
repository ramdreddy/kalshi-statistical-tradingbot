"""Weather metric feeder (dummy data for development)."""

import asyncio
import logging
import math
from collections.abc import AsyncIterator

from kalshi_bot.domain.models import WeatherMetrics

logger = logging.getLogger(__name__)


class WeatherFeeder:
    """
    Polls dummy weather observations on a fixed interval.

    Replace `fetch_metrics` with a real NOAA/Open-Meteo client for production.
    """

    def __init__(
        self,
        location: str = "New York, NY",
        poll_interval_sec: float = 5.0,
    ) -> None:
        self._location = location
        self._poll_interval_sec = poll_interval_sec
        self._tick = 0

    async def fetch_metrics(self) -> WeatherMetrics:
        """Return synthetic weather readings that drift over time."""
        self._tick += 1
        # Smooth oscillation around 74°F to exercise strategy paths.
        base_temp = 74.0 + 3.0 * math.sin(self._tick / 4.0)
        return WeatherMetrics(
            location=self._location,
            temperature_f=round(base_temp, 1),
            humidity_pct=round(55.0 + 10.0 * math.cos(self._tick / 5.0), 1),
            wind_speed_mph=round(8.0 + 2.0 * math.sin(self._tick / 3.0), 1),
        )

    async def stream(self) -> AsyncIterator[WeatherMetrics]:
        """Yield weather metrics until the caller cancels the task."""
        while True:
            metrics = await self.fetch_metrics()
            logger.debug(
                "weather update location=%s temp=%.1f°F humidity=%.1f%%",
                metrics.location,
                metrics.temperature_f,
                metrics.humidity_pct,
            )
            yield metrics
            await asyncio.sleep(self._poll_interval_sec)
