"""Trading engine: wires feeds, mock exchange, and strategy evaluation."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from kalshi_bot.config import Settings
from kalshi_bot.domain.events import Event, EventType
from kalshi_bot.domain.models import ImbalanceSignal, OrderBookSnapshot, WeatherMetrics
from kalshi_bot.engine.bus import EventBus
from kalshi_bot.engine.signal_selection import SizedSignal, rank_signals_by_edge
from kalshi_bot.exchange.kalshi_rest import fetch_account_balance_dollars
from kalshi_bot.exchange.order_executor import OrderExecutor
from kalshi_bot.feeds.weather import WeatherFeeder
from kalshi_bot.risk.kelly import KellyAllocation
from kalshi_bot.risk.sizing import size_signal
from kalshi_bot.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)


class TradingEngine:
    """Coordinates async producers and strategy evaluation on the event bus."""

    def __init__(
        self,
        bus: EventBus,
        strategy: BaseStrategy,
        weather_feeder: WeatherFeeder,
        orderbook_ws: Any,
        settings: Settings,
        order_executor: OrderExecutor | None = None,
    ) -> None:
        self._bus = bus
        self._strategy = strategy
        self._weather_feeder = weather_feeder
        self._orderbook_ws = orderbook_ws
        self._settings = settings
        self._order_executor = order_executor or OrderExecutor(settings)
        self._latest_orderbook: OrderBookSnapshot | None = None
        self._books_by_ticker: dict[str, OrderBookSnapshot] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._balance_dollars: float | None = None
        self._balance_fetched_at: float = 0.0
        self._signal_logged_at: dict[str, float] = {}
        self._last_book_quote: dict[str, tuple[int | None, int | None]] = {}
        self._last_signal_fingerprint: dict[str, tuple[int, int, str]] = {}
        self._batch_task: asyncio.Task[None] | None = None

    def _register_handlers(self) -> None:
        self._bus.subscribe(EventType.ORDERBOOK, self._on_orderbook)
        self._bus.subscribe(EventType.WEATHER, self._on_weather)

    def _use_best_edge_selection(self) -> bool:
        return self._settings.order_selection_mode.strip().lower() == "best_edge"

    async def _account_balance(self) -> float:
        now = time.monotonic()
        if (
            self._balance_dollars is not None
            and now - self._balance_fetched_at < self._settings.balance_cache_sec
        ):
            return self._balance_dollars
        self._balance_dollars = await fetch_account_balance_dollars(self._settings)
        self._balance_fetched_at = now
        return self._balance_dollars

    def seed_weather(self, metrics_list: list[WeatherMetrics]) -> None:
        """Load per-city forecasts before the first order-book evaluation."""
        for metrics in metrics_list:
            self._strategy.on_weather(metrics)

    async def _on_orderbook(self, event: Event) -> None:
        book: OrderBookSnapshot = event.payload
        ticker = book.ticker.upper()
        quote = (book.best_bid_cents, book.best_ask_cents)
        if quote == (None, None):
            return
        if self._last_book_quote.get(ticker) == quote:
            return
        self._last_book_quote[ticker] = quote
        self._latest_orderbook = book
        self._books_by_ticker[ticker] = book
        self._strategy.on_orderbook(book)

        if self._use_best_edge_selection():
            self._schedule_batch_evaluation()
        else:
            await self._evaluate(book)

    async def _on_weather(self, event: Event) -> None:
        weather: WeatherMetrics = event.payload
        self._strategy.on_weather(weather)
        self._clear_signal_cache_on_weather()
        self._last_book_quote.clear()

        if self._use_best_edge_selection():
            if self._batch_task and not self._batch_task.done():
                self._batch_task.cancel()
            await self._evaluate_best_edges()
        elif self._latest_orderbook is not None:
            await self._evaluate(self._latest_orderbook)

    def _schedule_batch_evaluation(self) -> None:
        if self._batch_task and not self._batch_task.done():
            self._batch_task.cancel()
        self._batch_task = asyncio.create_task(
            self._debounced_batch_evaluation(),
            name="best-edge-batch",
        )

    async def _debounced_batch_evaluation(self) -> None:
        try:
            await asyncio.sleep(self._settings.order_batch_debounce_sec)
            await self._evaluate_best_edges()
        except asyncio.CancelledError:
            pass

    def _should_log_signal(self, signal_key: str, signal: ImbalanceSignal) -> bool:
        fingerprint = (signal.edge_cents, signal.market_price_cents, signal.side.value)
        if self._last_signal_fingerprint.get(signal_key) == fingerprint:
            return False
        now = time.monotonic()
        last = self._signal_logged_at.get(signal_key)
        if last is not None and now - last < self._settings.signal_log_cooldown_sec:
            return False
        self._signal_logged_at[signal_key] = now
        self._last_signal_fingerprint[signal_key] = fingerprint
        return True

    def _clear_signal_cache_on_weather(self) -> None:
        """New forecast — allow fresh signals on the next book move."""
        self._last_signal_fingerprint.clear()
        self._signal_logged_at.clear()

    async def _collect_sized_signals(
        self,
        account_balance: float,
    ) -> list[SizedSignal]:
        candidates: list[SizedSignal] = []
        for book in self._books_by_ticker.values():
            signal = self._strategy.evaluate_imbalance(book, None)
            if signal is None:
                continue
            allocation = size_signal(
                signal,
                bet_size_dollars=self._settings.bet_size_dollars,
                account_balance_dollars=account_balance,
                min_account_balance_dollars=self._settings.min_account_balance_dollars,
                max_contracts_per_order=self._settings.max_contracts_per_order,
            )
            if allocation.contracts < 1:
                continue
            candidates.append(SizedSignal(signal=signal, allocation=allocation))
        return candidates

    def _log_signal(self, signal: ImbalanceSignal, allocation: KellyAllocation) -> None:
        signal_key = f"{signal.ticker}:{signal.side.value}"
        if not self._should_log_signal(signal_key, signal):
            return
        logger.info(
            "signal ticker=%s side=%s edge=%dc confidence=%.2f reason=%s",
            signal.ticker,
            signal.side.value,
            signal.edge_cents,
            signal.confidence,
            signal.reason,
        )
        logger.info(
            "size order: contracts=%d capital=$%.2f (target_bet=$%.2f)",
            allocation.contracts,
            allocation.capital_deployed_dollars,
            self._settings.bet_size_dollars,
        )

    async def _evaluate_best_edges(self) -> None:
        if not self._books_by_ticker:
            return

        account_balance = await self._account_balance()
        candidates = await self._collect_sized_signals(account_balance)
        if not candidates:
            return

        ranked = rank_signals_by_edge(candidates)

        for sized in ranked:
            self._log_signal(sized.signal, sized.allocation)

        if account_balance < self._settings.min_account_balance_dollars:
            logger.warning(
                "skip orders: account balance $%.2f below minimum $%.2f",
                account_balance,
                self._settings.min_account_balance_dollars,
            )
            for sized in ranked:
                await self._bus.publish(
                    Event(type=EventType.SIGNAL, payload=sized.signal)
                )
            return

        slots = self._order_executor.remaining_session_slots()
        if slots <= 0:
            logger.info(
                "skip orders: session limit %d reached (%d signals ranked)",
                self._settings.max_orders_per_session,
                len(ranked),
            )
            for sized in ranked:
                await self._bus.publish(
                    Event(type=EventType.SIGNAL, payload=sized.signal)
                )
            return

        to_trade = ranked[:slots]
        if len(to_trade) < len(ranked):
            logger.info(
                "best-edge selection: placing top %d of %d signals (max_orders=%d)",
                len(to_trade),
                len(ranked),
                self._settings.max_orders_per_session,
            )

        for sized in ranked:
            await self._bus.publish(Event(type=EventType.SIGNAL, payload=sized.signal))

        if not self._settings.trading_enabled:
            if to_trade:
                logger.info(
                    "trading disabled (set TRADING_ENABLED=true to place real orders)"
                )
            return

        for sized in to_trade:
            placed = await self._order_executor.maybe_execute(
                sized.signal,
                sized.allocation,
            )
            if placed is not None:
                logger.info(
                    "executed order id=%s ticker=%s side=%s edge=%dc count=%d price=%dc status=%s",
                    placed.order_id,
                    placed.ticker,
                    placed.side.value,
                    sized.signal.edge_cents,
                    placed.count,
                    placed.price_cents,
                    placed.status,
                )

    async def _evaluate(self, orderbook: OrderBookSnapshot) -> None:
        signal = self._strategy.evaluate_imbalance(orderbook, None)
        if signal is None:
            return

        signal_key = f"{signal.ticker}:{signal.side.value}"
        if not self._should_log_signal(signal_key, signal):
            return

        account_balance = await self._account_balance()
        allocation = size_signal(
            signal,
            bet_size_dollars=self._settings.bet_size_dollars,
            account_balance_dollars=account_balance,
            min_account_balance_dollars=self._settings.min_account_balance_dollars,
            max_contracts_per_order=self._settings.max_contracts_per_order,
        )

        logger.info(
            "signal ticker=%s side=%s edge=%dc confidence=%.2f reason=%s",
            signal.ticker,
            signal.side.value,
            signal.edge_cents,
            signal.confidence,
            signal.reason,
        )

        if account_balance < self._settings.min_account_balance_dollars:
            logger.warning(
                "skip order: account balance $%.2f below minimum $%.2f",
                account_balance,
                self._settings.min_account_balance_dollars,
            )
        elif allocation.contracts == 0:
            logger.info(
                "skip order: sized to 0 contracts (ev=%.1fc bet_size=$%.2f)",
                allocation.expected_value_cents,
                self._settings.bet_size_dollars,
            )
        else:
            logger.info(
                "size order: contracts=%d capital=$%.2f (target_bet=$%.2f account=$%.2f)",
                allocation.contracts,
                allocation.capital_deployed_dollars,
                self._settings.bet_size_dollars,
                account_balance,
            )
            if self._settings.trading_enabled:
                placed = await self._order_executor.maybe_execute(signal, allocation)
                if placed is not None:
                    logger.info(
                        "executed order id=%s ticker=%s side=%s count=%d price=%dc status=%s",
                        placed.order_id,
                        placed.ticker,
                        placed.side.value,
                        placed.count,
                        placed.price_cents,
                        placed.status,
                    )
            else:
                logger.info(
                    "trading disabled (set TRADING_ENABLED=true to place real orders)"
                )

        await self._bus.publish(Event(type=EventType.SIGNAL, payload=signal))

    async def _produce_weather(self) -> None:
        async for metrics in self._weather_feeder.stream():
            await self._bus.publish(Event(type=EventType.WEATHER, payload=metrics))

    async def _produce_orderbook(self) -> None:
        async for snapshot in self._orderbook_ws.stream():
            await self._bus.publish(Event(type=EventType.ORDERBOOK, payload=snapshot))

    async def _heartbeat(self) -> None:
        interval = max(60.0, self._settings.weather_poll_interval_sec)
        while True:
            await asyncio.sleep(interval)
            logger.info(
                "bot alive — waiting for books/signals (trading_enabled=%s selection=%s)",
                self._settings.trading_enabled,
                self._settings.order_selection_mode,
            )

    async def run(self) -> None:
        self._register_handlers()
        self._tasks = [
            asyncio.create_task(self._produce_weather(), name="weather-producer"),
            asyncio.create_task(self._produce_orderbook(), name="orderbook-producer"),
            asyncio.create_task(self._bus.run(), name="event-bus"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
        ]
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            await self._shutdown()

    async def _shutdown(self) -> None:
        if self._batch_task and not self._batch_task.done():
            self._batch_task.cancel()
        await self._bus.stop()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
