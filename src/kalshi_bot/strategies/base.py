"""Abstract strategy interface for event-driven trading logic."""

from __future__ import annotations

from abc import ABC, abstractmethod

from kalshi_bot.domain.models import ImbalanceSignal, OrderBookSnapshot, WeatherMetrics


class BaseStrategy(ABC):
    """Strategy plugins evaluate market state and emit trade signals."""

    @abstractmethod
    def evaluate_imbalance(
        self,
        orderbook: OrderBookSnapshot,
        weather: WeatherMetrics | None,
    ) -> ImbalanceSignal | None:
        """
        Inspect order-book depth vs. external weather context.

        Returns an imbalance signal when the strategy detects actionable edge,
        otherwise None.
        """

    def on_orderbook(self, orderbook: OrderBookSnapshot) -> ImbalanceSignal | None:
        """Hook for order-book-only updates (default: no signal)."""
        return None

    def on_weather(self, weather: WeatherMetrics) -> None:
        """Optional hook when fresh weather metrics arrive."""
