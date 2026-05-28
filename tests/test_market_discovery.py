from kalshi_bot.domain.market import BracketStrikeType
from kalshi_bot.exchange.market_discovery import (
    _select_primary_event,
    parse_weather_market,
    resolve_weather_series_tickers,
)
from kalshi_bot.feeds.weather_locations import (
    dedupe_series_by_city,
    is_weather_series_ticker,
)


def test_parse_between_bracket_from_strikes() -> None:
    market = parse_weather_market(
        {
            "ticker": "KXHIGHNY-26MAY27-B79",
            "event_ticker": "KXHIGHNY-26MAY27",
            "title": "79° to 80°",
            "strike_type": "between",
            "floor_strike": 79,
            "cap_strike": 80,
        }
    )
    assert market is not None
    assert market.strike_type == BracketStrikeType.BETWEEN
    assert market.floor_f == 79
    assert market.cap_f == 80
    assert market.series_ticker == "KXHIGHNY"


def test_parse_bracket_from_title_when_strikes_missing() -> None:
    market = parse_weather_market(
        {
            "ticker": "KXHIGHNY-26MAY27-B77",
            "event_ticker": "KXHIGHNY-26MAY27",
            "title": "77° to 78°",
        }
    )
    assert market is not None
    assert market.strike_type == BracketStrikeType.BETWEEN
    assert market.floor_f == 77
    assert market.cap_f == 78


def test_parse_less_than_threshold_ticker() -> None:
    market = parse_weather_market(
        {
            "ticker": "KXHIGHAUS-26MAY28-T86",
            "event_ticker": "KXHIGHAUS-26MAY28",
            "title": "Will the high temp in Austin be <86° on May 28, 2026?",
        }
    )
    assert market is not None
    assert market.strike_type == BracketStrikeType.LESS_OR_EQUAL
    assert market.cap_f == 85


def test_parse_legacy_threshold_ticker() -> None:
    market = parse_weather_market(
        {
            "ticker": "KXHIGHNY-26MAY24-T75",
            "event_ticker": "KXHIGHNY-26MAY24",
            "title": "75° or above",
            "strike_type": "greater_or_equal",
            "floor_strike": 75,
        }
    )
    assert market is not None
    assert market.strike_type == BracketStrikeType.GREATER_OR_EQUAL
    assert market.floor_f == 75


def test_select_primary_event_prefers_latest_close() -> None:
    event = _select_primary_event(
        [
            {
                "event_ticker": "KXHIGHNY-OLD",
                "close_time": "2026-05-25T23:59:00Z",
                "volume_fp": "10",
            },
            {
                "event_ticker": "KXHIGHNY-NEW",
                "close_time": "2026-05-27T23:59:00Z",
                "volume_fp": "5",
            },
        ]
    )
    assert event == "KXHIGHNY-NEW"


def test_is_weather_series_ticker() -> None:
    assert is_weather_series_ticker("KXHIGHTNYC")
    assert is_weather_series_ticker("KXHIGHNY")
    assert not is_weather_series_ticker("KXLOWCHI")
    assert not is_weather_series_ticker("KXRAINNYC")
    assert not is_weather_series_ticker("KXHIGHINFLATION")
    assert not is_weather_series_ticker("FED")


def test_dedupe_series_prefers_kxhight() -> None:
    result = dedupe_series_by_city(["KXHIGHCHI", "KXHIGHTCHI", "KXHIGHTMIA"])
    assert "KXHIGHTCHI" in result
    assert "KXHIGHCHI" not in result
    assert "KXHIGHTMIA" in result


def test_resolve_series_single_scope() -> None:
    from kalshi_bot.config import Settings

    settings = Settings(
        _env_file=None,
        weather_discovery_scope="single",
        weather_series_ticker="KXHIGHMIA",
    )

    async def _run() -> list[str]:
        return await resolve_weather_series_tickers(settings)

    import asyncio

    assert asyncio.run(_run()) == ["KXHIGHMIA"]
