import asyncio
from datetime import date

from kalshi_bot.domain.models import WeatherMetrics
from kalshi_bot.feeds.composite import CompositeWeatherFeeder
from kalshi_bot.feeds.twc import select_twc_daily_high
from kalshi_bot.feeds.weather import WeatherFeeder


def test_twc_picks_settlement_day_calendar_high() -> None:
    payload = {
        "validTimeLocal": ["2026-11-18T07:00:00-0600", "2026-11-19T07:00:00-0600", "2026-11-20T07:00:00-0600"],
        "calendarDayTemperatureMax": [64, 67, 70],
    }
    assert select_twc_daily_high(payload, date(2026, 11, 19)) == 67.0
    assert select_twc_daily_high(payload, date(2026, 11, 25)) is None


def test_twc_skips_missing_values() -> None:
    payload = {"validTimeLocal": ["2026-11-18T07:00:00-0600"], "calendarDayTemperatureMax": [None]}
    assert select_twc_daily_high(payload, date(2026, 11, 18)) is None


class _Fixed(WeatherFeeder):
    def __init__(self, source: str, temp: float) -> None:
        super().__init__(location=source, poll_interval_sec=0.01)
        self._m = WeatherMetrics(source, temp, 0, 0, forecast_high_f=temp, source=source, series_ticker="KXHIGHNY")

    async def fetch_metrics(self) -> WeatherMetrics:
        return self._m

    async def warm_up(self) -> list[WeatherMetrics]:
        return [self._m]


def test_composite_warm_up_and_stream_include_every_source() -> None:
    comp = CompositeWeatherFeeder([_Fixed("nws:KXHIGHNY", 61), _Fixed("twc:KXHIGHNY", 64)])

    async def run():
        warm = await comp.warm_up()
        seen = set()
        stream = comp.stream()
        while len(seen) < 2:
            seen.add((await stream.__anext__()).source)
        await stream.aclose()
        return {m.source for m in warm}, seen

    warm, streamed = asyncio.run(run())
    assert warm == streamed == {"nws:KXHIGHNY", "twc:KXHIGHNY"}
