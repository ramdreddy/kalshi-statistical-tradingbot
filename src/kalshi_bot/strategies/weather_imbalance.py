"""Public placeholder strategy."""

from __future__ import annotations

from kalshi_bot.domain.models import ImbalanceSignal, OrderBookSnapshot, WeatherMetrics
from kalshi_bot.strategies.base import BaseStrategy


class WeatherImbalanceStrategy(BaseStrategy):
    @classmethod
    def from_markets(cls, markets, **kwargs):
        return cls()

    def on_weather(self, weather: WeatherMetrics) -> None:
        return None

    def evaluate_imbalance(
        self, orderbook: OrderBookSnapshot, weather: WeatherMetrics | None
    ) -> ImbalanceSignal | None:
        return None
