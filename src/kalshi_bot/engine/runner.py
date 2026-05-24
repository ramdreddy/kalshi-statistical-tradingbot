"""Trading engine: wires feeds, mock exchange, and strategy evaluation."""

from __future__ import annotations

import asyncio
import logging

from kalshi_bot.domain.events import Event, EventType
from kalshi_bot.domain.models import OrderBookSnapshot, WeatherMetrics
from kalshi_bot.engine.bus import EventBus
from kalshi_bot.exchange.mock_ws import MockKalshiOrderBookWebSocket
from kalshi_bot.feeds.weather import WeatherFeeder
from kalshi_bot.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class TradingEngine:
    """Coordinates async producers and strategy evaluation on the event bus."""

    def __init__(
        self,
        bus: EventBus,
        strategy: BaseStrategy,
        weather_feeder: WeatherFeeder,
        orderbook_ws: MockKalshiOrderBookWebSocket,
    ) -> None:
        self._bus = bus
        self._strategy = strategy
        self._weather_feeder = weather_feeder
        self._orderbook_ws = orderbook_ws
        self._latest_orderbook: OrderBookSnapshot | None = None
        self._latest_weather: WeatherMetrics | None = None
        self._tasks: list[asyncio.Task[None]] = []

    def _register_handlers(self) -> None:
        self._bus.subscribe(EventType.ORDERBOOK, self._on_orderbook)
        self._bus.subscribe(EventType.WEATHER, self._on_weather)

    async def _on_orderbook(self, event: Event) -> None:
        book: OrderBookSnapshot = event.payload
        self._latest_orderbook = book
        self._strategy.on_orderbook(book)
        await self._evaluate(book)

    async def _on_weather(self, event: Event) -> None:
        weather: WeatherMetrics = event.payload
        self._latest_weather = weather
        self._strategy.on_weather(weather)
        if self._latest_orderbook is not None:
            await self._evaluate(self._latest_orderbook)

    async def _evaluate(self, orderbook: OrderBookSnapshot) -> None:
        signal = self._strategy.evaluate_imbalance(orderbook, self._latest_weather)
        if signal is None:
            return
        logger.info(
            "signal ticker=%s side=%s edge=%dc confidence=%.2f reason=%s",
            signal.ticker,
            signal.side.value,
            signal.edge_cents,
            signal.confidence,
            signal.reason,
        )
        await self._bus.publish(Event(type=EventType.SIGNAL, payload=signal))

    async def _produce_weather(self) -> None:
        async for metrics in self._weather_feeder.stream():
            await self._bus.publish(Event(type=EventType.WEATHER, payload=metrics))

    async def _produce_orderbook(self) -> None:
        async for snapshot in self._orderbook_ws.stream():
            await self._bus.publish(Event(type=EventType.ORDERBOOK, payload=snapshot))

    async def run(self) -> None:
        self._register_handlers()
        self._tasks = [
            asyncio.create_task(self._produce_weather(), name="weather-producer"),
            asyncio.create_task(self._produce_orderbook(), name="orderbook-producer"),
            asyncio.create_task(self._bus.run(), name="event-bus"),
        ]
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            await self._shutdown()

    async def _shutdown(self) -> None:
        await self._bus.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
