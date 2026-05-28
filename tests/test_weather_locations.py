from kalshi_bot.feeds.weather_locations import (
    location_for_series,
    series_ticker_from_market_ticker,
)


def test_series_from_market_ticker() -> None:
    assert series_ticker_from_market_ticker("KXHIGHCHI-26MAY27-B80") == "KXHIGHCHI"


def test_location_for_known_series() -> None:
    loc = location_for_series("KXHIGHNY")
    assert loc is not None
    assert "New York" in loc.label
