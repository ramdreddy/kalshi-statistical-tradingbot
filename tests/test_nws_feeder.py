from datetime import date
from zoneinfo import ZoneInfo

import pytest

from kalshi_bot.feeds.nws import NWSFeeder


@pytest.mark.asyncio
async def test_fetch_metrics_uses_forecast_and_observed(monkeypatch) -> None:
    feeder = NWSFeeder(
        40.7812,
        -73.9665,
        user_agent="test-agent",
        forecast_date=date(2026, 5, 27),
        timezone=ZoneInfo("America/New_York"),
    )

    async def fake_forecast(client) -> tuple[float, str]:
        return 85.0, "Thursday"

    async def fake_observed(client) -> float:
        return 80.0

    monkeypatch.setattr(feeder, "_forecast_high_f", fake_forecast)
    monkeypatch.setattr(feeder, "_observed_high_so_far_f", fake_observed)
    monkeypatch.setattr(
        "kalshi_bot.feeds.nws.datetime",
        type(
            "DT",
            (),
            {
                "now": staticmethod(
                    lambda tz: __import__("datetime").datetime(
                        2026, 5, 27, 12, 0, tzinfo=tz
                    )
                ),
                "combine": __import__("datetime").datetime.combine,
                "min": __import__("datetime").datetime.min,
            },
        ),
    )

    metrics = await feeder.fetch_metrics()
    assert metrics.source == "nws"
    assert metrics.forecast_high_f == 85.0
    assert metrics.observed_high_f == 80.0
    assert metrics.temperature_f == 85.0


@pytest.mark.asyncio
async def test_fetch_metrics_skips_observed_for_future_settlement_day(monkeypatch) -> None:
    feeder = NWSFeeder(
        30.1975,
        -97.6664,
        user_agent="test-agent",
        forecast_date=date(2026, 5, 28),
        timezone=ZoneInfo("America/Chicago"),
    )

    async def fake_forecast(client) -> tuple[float, str]:
        return 89.0, "Thursday"

    observed_called = False

    async def fake_observed(client) -> float:
        nonlocal observed_called
        observed_called = True
        return 84.0

    monkeypatch.setattr(feeder, "_forecast_high_f", fake_forecast)
    monkeypatch.setattr(feeder, "_observed_high_so_far_f", fake_observed)
    monkeypatch.setattr(
        "kalshi_bot.feeds.nws.datetime",
        type(
            "DT",
            (),
            {
                "now": staticmethod(
                    lambda tz: __import__("datetime").datetime(
                        2026, 5, 27, 19, 0, tzinfo=tz
                    )
                ),
                "combine": __import__("datetime").datetime.combine,
                "min": __import__("datetime").datetime.min,
            },
        ),
    )

    metrics = await feeder.fetch_metrics()
    assert metrics.forecast_high_f == 89.0
    assert metrics.observed_high_f is None
    assert metrics.temperature_f == 89.0
    assert observed_called is False
