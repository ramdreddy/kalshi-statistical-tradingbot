"""
NWS (weather.gov) feeder aligned with Kalshi daily-high settlement.

Uses the official NWS API (no key required) to fetch:
- Forecast daily high for the gridpoint at the configured station lat/lon
- Running observed high so far today from the nearest NWS observation station

Kalshi settles on the NWS Climatological Report (CLI) daily maximum. Forecast
high is the appropriate pre-settlement signal; CLI is only final after the day.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from kalshi_bot.domain.models import WeatherMetrics
from kalshi_bot.feeds.weather import WeatherFeeder

logger = logging.getLogger(__name__)

_NWS_BASE = "https://api.weather.gov"


@dataclass(frozen=True)
class _ForecastDayMatch:
    """Forecast daily high for a Kalshi settlement date."""

    target_date: date
    source_label: str
    temperature_f: float


def _c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def _local_date_from_period(start_time: str, tz: ZoneInfo) -> date:
    dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    return dt.astimezone(tz).date()


def select_forecast_high_from_hourly(
    periods: list[dict],
    target_date: date,
    tz: ZoneInfo,
) -> _ForecastDayMatch | None:
    """
    Daily high = max hourly ``temperature`` on the settlement date (local time).

    Aligns with weather.gov “high” and Kalshi-style daily maximum better than
    the single integer on a 12-hour daytime period block.
    """
    hourly_temps: list[int] = []
    for period in periods:
        start_time = period.get("startTime")
        temp = period.get("temperature")
        if not start_time or temp is None:
            continue
        if _local_date_from_period(start_time, tz) != target_date:
            continue
        hourly_temps.append(int(temp))

    if not hourly_temps:
        return None

    return _ForecastDayMatch(
        target_date=target_date,
        source_label="hourly max",
        temperature_f=float(max(hourly_temps)),
    )


def select_forecast_high_for_date(
    periods: list[dict],
    target_date: date,
    tz: ZoneInfo,
) -> _ForecastDayMatch | None:
    """
    Fallback: daytime block ``temperature`` on the settlement date (12-period).

    Returns ``None`` when no daytime period matches (never use other days).
    """
    matches: list[tuple[str, int]] = []
    for period in periods:
        if not period.get("isDaytime", True):
            continue
        start_time = period.get("startTime")
        if not start_time:
            continue
        if _local_date_from_period(start_time, tz) != target_date:
            continue
        matches.append((str(period.get("name") or ""), int(period["temperature"])))

    if not matches:
        return None

    name, temp = max(matches, key=lambda item: item[1])
    return _ForecastDayMatch(
        target_date=target_date,
        source_label=f"12-period {name}".strip(),
        temperature_f=float(temp),
    )


class NWSFeeder(WeatherFeeder):
    """
    Pull NWS forecast high and same-day observed max for a lat/lon.

    Default coordinates should match the station named in the Kalshi contract
    rules (e.g. Central Park for NYC high-temp markets).
    """

    def __init__(
        self,
        latitude: float,
        longitude: float,
        location: str = "NWS station",
        poll_interval_sec: float = 300.0,
        user_agent: str = "kalshi-weather-bot/0.1.0",
        series_ticker: str | None = None,
        forecast_date: date | None = None,
        timezone: ZoneInfo | None = None,
    ) -> None:
        super().__init__(location=location, poll_interval_sec=poll_interval_sec)
        self._latitude = latitude
        self._longitude = longitude
        self._series_ticker = series_ticker.upper() if series_ticker else None
        self._forecast_date = forecast_date
        self._timezone = timezone or ZoneInfo("America/New_York")
        self._headers = {
            "User-Agent": user_agent,
            "Accept": "application/geo+json",
        }

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> dict:
        response = await client.get(url, headers=self._headers, follow_redirects=True)
        response.raise_for_status()
        return response.json()

    async def _forecast_high_f(self, client: httpx.AsyncClient) -> tuple[float, str]:
        if self._forecast_date is None:
            raise ValueError(
                "NWSFeeder requires forecast_date (Kalshi event settlement day)"
            )

        points_url = f"{_NWS_BASE}/points/{self._latitude:.4f},{self._longitude:.4f}"
        points = await self._get_json(client, points_url)
        props = points.get("properties") or {}

        match: _ForecastDayMatch | None = None
        hourly_url = props.get("forecastHourly")
        if hourly_url:
            try:
                hourly = await self._get_json(client, str(hourly_url))
                match = select_forecast_high_from_hourly(
                    hourly.get("properties", {}).get("periods") or [],
                    self._forecast_date,
                    self._timezone,
                )
            except Exception:
                logger.warning(
                    "NWS hourly forecast fetch failed; falling back to 12-period",
                    exc_info=True,
                )

        if match is None:
            forecast_url = props.get("forecast")
            if not forecast_url:
                raise ValueError("NWS points response missing forecast URL")
            forecast = await self._get_json(client, str(forecast_url))
            periods = forecast.get("properties", {}).get("periods") or []
            match = select_forecast_high_for_date(
                periods,
                self._forecast_date,
                self._timezone,
            )
            if match is None:
                available = [
                    f"{p.get('name')}|{_local_date_from_period(p['startTime'], self._timezone)}"
                    for p in periods
                    if p.get("isDaytime", True) and p.get("startTime")
                ]
                raise ValueError(
                    f"No NWS forecast for settlement date={self._forecast_date} "
                    f"tz={self._timezone.key}; daytime periods: {available[:14]}"
                )
            logger.warning(
                "using 12-period forecast (hourly unavailable) day=%s high=%.0f°F",
                match.target_date,
                match.temperature_f,
            )

        logger.info(
            "nws forecast day=%s high=%.0f°F (%s, settlement-aligned)",
            match.target_date,
            match.temperature_f,
            match.source_label,
        )
        return match.temperature_f, match.source_label

    async def _observed_high_so_far_f(self, client: httpx.AsyncClient) -> float | None:
        points_url = f"{_NWS_BASE}/points/{self._latitude:.4f},{self._longitude:.4f}"
        points = await self._get_json(client, points_url)
        stations_url = points["properties"]["observationStations"]
        stations = await self._get_json(client, stations_url)

        features = stations.get("features") or []
        if not features:
            return None

        station_id = features[0]["properties"]["stationIdentifier"]
        local_today = datetime.now(self._timezone).date()
        start = datetime.combine(local_today, datetime.min.time(), tzinfo=self._timezone)
        obs_url = (
            f"{_NWS_BASE}/stations/{station_id}/observations"
            f"?start={start.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')}"
        )
        observations = await self._get_json(client, obs_url)

        highs: list[float] = []
        for feature in observations.get("features") or []:
            props = feature.get("properties") or {}
            temp_c = props.get("temperature", {}).get("value")
            if temp_c is None:
                continue
            highs.append(_c_to_f(float(temp_c)))

        return max(highs) if highs else None

    async def fetch_metrics(self) -> WeatherMetrics:
        async with httpx.AsyncClient(timeout=20.0) as client:
            forecast_high, _period_name = await self._forecast_high_f(client)

            local_today = datetime.now(self._timezone).date()
            use_observed = (
                self._forecast_date is not None and self._forecast_date == local_today
            )
            observed_high: float | None = None
            if use_observed:
                try:
                    observed_high = await self._observed_high_so_far_f(client)
                except Exception:
                    logger.warning("NWS observed-high fetch failed", exc_info=True)

        primary = forecast_high
        if observed_high is not None:
            primary = max(forecast_high, observed_high)

        source = f"nws:{self._series_ticker}" if self._series_ticker else "nws"
        return WeatherMetrics(
            location=self._location,
            temperature_f=round(primary, 1),
            humidity_pct=0.0,
            wind_speed_mph=0.0,
            forecast_high_f=round(forecast_high, 1),
            observed_high_f=round(observed_high, 1) if observed_high is not None else None,
            source=source,
            series_ticker=self._series_ticker,
        )

    async def stream(self) -> AsyncIterator[WeatherMetrics]:
        while True:
            try:
                metrics = await self.fetch_metrics()
                series = f" series={metrics.series_ticker}" if metrics.series_ticker else ""
                target = (
                    f" settlement_day={self._forecast_date}"
                    if self._forecast_date
                    else ""
                )
                logger.info(
                    "nws update location=%s%s%s forecast_high=%.1f°F observed_high=%s",
                    metrics.location,
                    series,
                    target,
                    metrics.forecast_high_f or metrics.temperature_f,
                    f"{metrics.observed_high_f:.1f}°F" if metrics.observed_high_f is not None else "n/a",
                )
                yield metrics
            except Exception:
                logger.exception("NWS fetch failed")
            await asyncio.sleep(self._poll_interval_sec)
