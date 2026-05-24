"""Example strategy: compare implied temperature market vs. observed weather."""

from __future__ import annotations

from kalshi_bot.domain.models import ImbalanceSignal, OrderBookSnapshot, Side, WeatherMetrics
from kalshi_bot.strategies.base import BaseStrategy


class WeatherImbalanceStrategy(BaseStrategy):
    """
    Demo strategy for weather high-temperature contracts.

    Uses mid-price as implied probability and compares against a crude
    temperature threshold heuristic when weather data is available.
    """

    def __init__(self, strike_temp_f: float = 75.0, min_edge_cents: int = 3) -> None:
        self._strike_temp_f = strike_temp_f
        self._min_edge_cents = min_edge_cents
        self._last_weather: WeatherMetrics | None = None

    def on_weather(self, weather: WeatherMetrics) -> None:
        self._last_weather = weather

    def evaluate_imbalance(
        self,
        orderbook: OrderBookSnapshot,
        weather: WeatherMetrics | None,
    ) -> ImbalanceSignal | None:
        metrics = weather or self._last_weather
        if metrics is None:
            return None

        bid = orderbook.best_bid_cents
        ask = orderbook.best_ask_cents
        if bid is None or ask is None:
            return None

        mid = (bid + ask) // 2
        # Simple heuristic: observed temp above strike favors YES settling.
        temp_edge = metrics.temperature_f - self._strike_temp_f
        fair_yes_cents = min(99, max(1, int(50 + temp_edge * 2)))

        edge = fair_yes_cents - mid
        if abs(edge) < self._min_edge_cents:
            return None

        side = Side.YES if edge > 0 else Side.NO
        return ImbalanceSignal(
            ticker=orderbook.ticker,
            side=side,
            edge_cents=abs(edge),
            confidence=min(1.0, abs(edge) / 20.0),
            reason=(
                f"observed {metrics.temperature_f:.1f}°F vs strike {self._strike_temp_f:.1f}°F; "
                f"mid={mid}c fair≈{fair_yes_cents}c"
            ),
        )
