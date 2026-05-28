from datetime import date

from kalshi_bot.domain.market import BracketStrikeType, WeatherBracketMarket
from kalshi_bot.feeds.event_dates import event_dates_by_series, parse_event_date_from_ticker


def test_parse_event_date_from_ticker() -> None:
    assert parse_event_date_from_ticker("KXHIGHAUS-26MAY28") == date(2026, 5, 28)
    assert parse_event_date_from_ticker("KXHIGHNY-26MAY27") == date(2026, 5, 27)
    assert parse_event_date_from_ticker("INVALID") is None


def test_event_dates_by_series() -> None:
    markets = [
        WeatherBracketMarket(
            ticker="KXHIGHAUS-26MAY28-B90.5",
            event_ticker="KXHIGHAUS-26MAY28",
            series_ticker="KXHIGHAUS",
            title="90-91",
            strike_type=BracketStrikeType.BETWEEN,
            floor_f=90,
            cap_f=91,
        ),
        WeatherBracketMarket(
            ticker="KXHIGHAUS-26MAY28-T93",
            event_ticker="KXHIGHAUS-26MAY28",
            series_ticker="KXHIGHAUS",
            title=">=93",
            strike_type=BracketStrikeType.GREATER_OR_EQUAL,
            floor_f=93,
        ),
    ]
    assert event_dates_by_series(markets) == {"KXHIGHAUS": date(2026, 5, 28)}
