"""Mock Kalshi order-book WebSocket subscription for local development."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator

from kalshi_bot.domain.models import OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger(__name__)


class MockKalshiOrderBookWebSocket:
    """
    Simulates a Kalshi `orderbook_delta` / snapshot stream.

    In production, replace with a real WebSocket client that authenticates
    against `Settings.kalshi_ws_url` and subscribes to `orderbook` channels.
    """

    def __init__(
        self,
        ticker: str | list[str],
        interval_sec: float = 1.0,
        seed: int | None = None,
    ) -> None:
        tickers = [ticker] if isinstance(ticker, str) else list(ticker)
        if not tickers:
            raise ValueError("At least one ticker is required")
        self._tickers = [t.upper() for t in tickers]
        self._ticker = self._tickers[0]
        self._interval_sec = interval_sec
        self._rng = random.Random(seed)
        self._mid_by_ticker = {t: 48 for t in self._tickers}
        self._cursor = 0

    async def connect(self) -> None:
        logger.info("mock ws connected ticker=%s", self._ticker)
        await asyncio.sleep(0.05)

    async def subscribe_orderbook(self, ticker: str | None = None) -> None:
        target = ticker or self._ticker
        logger.info("mock ws subscribed channel=orderbook ticker=%s", target)

    async def disconnect(self) -> None:
        logger.info("mock ws disconnected ticker=%s", self._ticker)

    def _next_snapshot(self) -> OrderBookSnapshot:
        ticker = self._tickers[self._cursor % len(self._tickers)]
        self._cursor += 1
        drift = self._rng.randint(-2, 2)
        mid = self._mid_by_ticker[ticker]
        mid = max(5, min(95, mid + drift))
        self._mid_by_ticker[ticker] = mid
        spread = self._rng.randint(2, 6)
        bid = mid - spread // 2
        ask = mid + (spread - spread // 2)

        def levels(anchor: int, descending: bool) -> tuple[OrderBookLevel, ...]:
            prices = [anchor + i * (1 if not descending else -1) for i in range(3)]
            return tuple(
                OrderBookLevel(price_cents=p, quantity=self._rng.randint(10, 200))
                for p in prices
            )

        return OrderBookSnapshot(
            ticker=ticker,
            yes_bids=levels(bid, descending=True),
            yes_asks=levels(ask, descending=False),
        )

    async def stream(self) -> AsyncIterator[OrderBookSnapshot]:
        """Yield synthetic order-book snapshots until cancelled."""
        await self.connect()
        await self.subscribe_orderbook()
        try:
            while True:
                snapshot = self._next_snapshot()
                logger.debug(
                    "orderbook update ticker=%s bid=%s ask=%s spread=%s",
                    snapshot.ticker,
                    snapshot.best_bid_cents,
                    snapshot.best_ask_cents,
                    snapshot.spread_cents,
                )
                yield snapshot
                await asyncio.sleep(self._interval_sec)
        finally:
            await self.disconnect()
