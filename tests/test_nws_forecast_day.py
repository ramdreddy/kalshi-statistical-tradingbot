from datetime import date
from zoneinfo import ZoneInfo

from kalshi_bot.feeds.nws import (
    select_forecast_high_for_date,
    select_forecast_high_from_hourly,
)


def _period(name: str, start: str, temp: int, *, daytime: bool = True) -> dict:
    return {
        "name": name,
        "startTime": start,
        "isDaytime": daytime,
        "temperature": temp,
    }


def _hourly(start: str, temp: int) -> dict:
    return {"startTime": start, "temperature": temp}


def test_hourly_max_matches_daily_high_not_block_temp() -> None:
    """Block Thursday=88 but hourly peaks at 89 → use 89."""
    hourly = [
        _hourly("2026-05-28T06:00:00-05:00", 70),
        _hourly("2026-05-28T14:00:00-05:00", 89),
        _hourly("2026-05-28T17:00:00-05:00", 86),
        _hourly("2026-05-29T14:00:00-05:00", 90),
    ]
    tz = ZoneInfo("America/Chicago")
    match = select_forecast_high_from_hourly(hourly, date(2026, 5, 28), tz)
    assert match is not None
    assert match.temperature_f == 89.0
    assert match.source_label == "hourly max"


def test_hourly_ignores_other_days() -> None:
    hourly = [
        _hourly("2026-05-27T14:00:00-05:00", 92),
        _hourly("2026-05-28T14:00:00-05:00", 89),
    ]
    match = select_forecast_high_from_hourly(
        hourly,
        date(2026, 5, 28),
        ZoneInfo("America/Chicago"),
    )
    assert match is not None
    assert match.temperature_f == 89.0


def test_select_forecast_high_uses_settlement_day_not_weekly_max() -> None:
    """12-period fallback: must not return Sunday 92 when Thursday settlement is 89."""
    periods = [
        _period("Wednesday", "2026-05-27T07:00:00-05:00", 88),
        _period("Thursday", "2026-05-28T07:00:00-05:00", 89),
        _period("Friday", "2026-05-29T07:00:00-05:00", 90),
        _period("Sunday", "2026-05-31T07:00:00-05:00", 92),
        _period("Thursday Night", "2026-05-28T19:00:00-05:00", 70, daytime=False),
    ]
    tz = ZoneInfo("America/Chicago")
    match = select_forecast_high_for_date(periods, date(2026, 5, 28), tz)
    assert match is not None
    assert match.temperature_f == 89.0
    assert "Thursday" in match.source_label


def test_select_forecast_high_returns_none_when_day_missing() -> None:
    periods = [_period("Friday", "2026-05-29T07:00:00-05:00", 90)]
    assert (
        select_forecast_high_for_date(
            periods,
            date(2026, 5, 28),
            ZoneInfo("America/Chicago"),
        )
        is None
    )
