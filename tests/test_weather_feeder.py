import pytest

from kalshi_bot.feeds.weather import WeatherFeeder


@pytest.mark.asyncio
async def test_fetch_metrics_returns_dummy_data() -> None:
    feeder = WeatherFeeder(location="Chicago, IL", poll_interval_sec=0.01)
    first = await feeder.fetch_metrics()
    second = await feeder.fetch_metrics()
    assert first.location == "Chicago, IL"
    assert 50.0 < first.temperature_f < 100.0
    assert first.temperature_f != second.temperature_f
