from kalshi_bot.domain.models import OrderBookLevel, OrderBookSnapshot, WeatherMetrics
from kalshi_bot.strategies.weather_imbalance import WeatherImbalanceStrategy


def _book(mid: int) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        ticker="KXHIGHNY-TEST",
        yes_bids=(OrderBookLevel(price_cents=mid - 1, quantity=100),),
        yes_asks=(OrderBookLevel(price_cents=mid + 1, quantity=100),),
    )


def test_evaluate_imbalance_returns_none_without_weather() -> None:
    strategy = WeatherImbalanceStrategy()
    assert strategy.evaluate_imbalance(_book(50), None) is None


def test_evaluate_imbalance_emits_signal_when_edge_large() -> None:
    strategy = WeatherImbalanceStrategy(strike_temp_f=70.0, min_edge_cents=1)
    weather = WeatherMetrics(
        location="NYC",
        temperature_f=85.0,
        humidity_pct=50.0,
        wind_speed_mph=5.0,
    )
    signal = strategy.evaluate_imbalance(_book(40), weather)
    assert signal is not None
    assert signal.edge_cents >= 1
