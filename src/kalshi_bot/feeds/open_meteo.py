"""Open-Meteo weather feed (free, no API key required)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import httpx

from kalshi_bot.domain.models import WeatherMetrics
from kalshi_bot.feeds.weather import WeatherFeeder

logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoFeeder(WeatherFeeder):
    """Pull current conditions from Open-Meteo."""

    def __init__(
        self,
        latitude: float,
        longitude: float,
        location: str = "Open-Meteo",
        poll_interval_sec: float = 300.0,
        api_url: str = _DEFAULT_URL,
    ) -> None:
        super().__init__(location=location, poll_interval_sec=poll_interval_sec)
        self._latitude = latitude
        self._longitude = longitude
        self._api_url = api_url

    async def fetch_metrics(self) -> WeatherMetrics:
        params = {
            "latitude": self._latitude,
            "longitude": self._longitude,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(self._api_url, params=params)
            response.raise_for_status()
            payload = response.json()

        current = payload["current"]
        # Open-Meteo wind is km/h when mph requested it converts; with wind_speed_unit=mph we're good.
        wind = float(current.get("wind_speed_10m") or 0.0)
        return WeatherMetrics(
            location=self._location,
            temperature_f=float(current["temperature_2m"]),
            humidity_pct=float(current["relative_humidity_2m"]),
            wind_speed_mph=wind,
            source="open_meteo",
        )

    async def stream(self) -> AsyncIterator[WeatherMetrics]:
        while True:
            try:
                metrics = await self.fetch_metrics()
                logger.info(
                    "open-meteo location=%s temp=%.1f°F humidity=%.1f%%",
                    metrics.location,
                    metrics.temperature_f,
                    metrics.humidity_pct,
                )
                yield metrics
            except Exception:
                logger.exception("open-meteo fetch failed")
            await asyncio.sleep(self._poll_interval_sec)
