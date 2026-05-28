"""Live Kalshi order-book WebSocket client."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from kalshi_bot.domain.models import OrderBookLevel, OrderBookSnapshot
from kalshi_bot.exchange.kalshi_auth import (
    build_auth_headers,
    load_private_key,
    ws_path_from_url,
)

logger = logging.getLogger(__name__)


def _price_to_cents(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 1 else value * 100
    if isinstance(value, float):
        return int(round(value * 100)) if value <= 1.0 else int(round(value))
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return int(round(parsed * 100)) if parsed <= 1.0 else int(round(parsed))
    return None


def _qty_from_value(value: Any) -> int:
    if isinstance(value, str):
        return int(float(value))
    return int(value)


def _levels_from_dollars_fp(raw_levels: Any) -> tuple[OrderBookLevel, ...]:
    """Parse [[price_dollars, qty_fp], ...] from Kalshi orderbook snapshots."""
    if not raw_levels:
        return ()
    levels: list[OrderBookLevel] = []
    for entry in raw_levels:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        price_cents = _price_to_cents(entry[0])
        if price_cents is None:
            continue
        levels.append(OrderBookLevel(price_cents=price_cents, quantity=_qty_from_value(entry[1])))
    return tuple(sorted(levels, key=lambda level: level.price_cents, reverse=True))


def _yes_asks_from_no_fp(no_levels: Any) -> tuple[OrderBookLevel, ...]:
    """Convert NO-side levels to implied YES ask prices (cents)."""
    asks: list[OrderBookLevel] = []
    for entry in no_levels or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        no_cents = _price_to_cents(entry[0])
        if no_cents is None:
            continue
        yes_ask_cents = 100 - no_cents
        asks.append(
            OrderBookLevel(price_cents=yes_ask_cents, quantity=_qty_from_value(entry[1]))
        )
    return tuple(sorted(asks, key=lambda level: level.price_cents))


def _levels_from_legacy(raw_levels: Any) -> tuple[OrderBookLevel, ...]:
    if not raw_levels:
        return ()
    levels: list[OrderBookLevel] = []
    for entry in raw_levels:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2:
            price_cents = _price_to_cents(entry[0])
            qty = _qty_from_value(entry[1])
        elif isinstance(entry, dict):
            price_cents = _price_to_cents(
                entry.get("price") or entry.get("price_cents") or entry.get("price_dollars")
            )
            qty = _qty_from_value(
                entry.get("quantity") or entry.get("qty") or entry.get("count") or 0
            )
        else:
            continue
        if price_cents is None:
            continue
        levels.append(OrderBookLevel(price_cents=price_cents, quantity=qty))
    return tuple(levels)


def snapshot_from_message(msg: dict[str, Any], ticker: str) -> OrderBookSnapshot | None:
    """Parse Kalshi orderbook_snapshot payloads (current dollars_fp format)."""
    market_ticker = str(msg.get("market_ticker") or ticker).upper()

    if msg.get("yes_dollars_fp") is not None or msg.get("no_dollars_fp") is not None:
        yes_bids = _levels_from_dollars_fp(msg.get("yes_dollars_fp"))
        yes_asks = _yes_asks_from_no_fp(msg.get("no_dollars_fp"))
        return OrderBookSnapshot(
            ticker=market_ticker,
            yes_bids=yes_bids,
            yes_asks=yes_asks,
        )

    yes_raw = msg.get("yes") or msg.get("yes_orders") or msg.get("bids")
    no_raw = msg.get("no") or msg.get("no_orders") or msg.get("asks")
    yes_bids = _levels_from_legacy(yes_raw)
    yes_asks = _levels_from_legacy(no_raw)

    if not yes_bids and msg.get("yes_bid_dollars") is not None:
        bid = _price_to_cents(msg.get("yes_bid_dollars"))
        ask = _price_to_cents(msg.get("yes_ask_dollars"))
        if bid is not None:
            yes_bids = (OrderBookLevel(price_cents=bid, quantity=1),)
        if ask is not None:
            yes_asks = (OrderBookLevel(price_cents=ask, quantity=1),)

    if not yes_bids and not yes_asks:
        # Kalshi sends ticker-only snapshots when the book has no resting orders.
        if msg.get("market_ticker"):
            return OrderBookSnapshot(
                ticker=market_ticker,
                yes_bids=(),
                yes_asks=(),
            )
        return None

    return OrderBookSnapshot(
        ticker=market_ticker,
        yes_bids=yes_bids,
        yes_asks=yes_asks,
    )


class KalshiOrderBookWebSocket:
    """Authenticated WebSocket streaming orderbook snapshots and deltas."""

    def __init__(
        self,
        ws_url: str,
        api_key_id: str,
        private_key_path: str,
        tickers: list[str],
        subscribe_batch_size: int = 20,
    ) -> None:
        if not tickers:
            raise ValueError("At least one market ticker is required")
        self._ws_url = ws_url
        self._api_key_id = api_key_id
        self._private_key_path = private_key_path
        self._tickers = [t.upper() for t in tickers]
        self._primary_ticker = self._tickers[0]
        self._msg_id = 1
        self._books: dict[str, OrderBookSnapshot] = {}
        self._subscribe_batch_size = max(1, subscribe_batch_size)

    async def connect(self) -> None:
        import websockets  # lazy import

        private_key = load_private_key(self._private_key_path)
        headers = build_auth_headers(
            self._api_key_id,
            private_key,
            path=ws_path_from_url(self._ws_url),
        )
        try:
            self._ws = await websockets.connect(
                self._ws_url,
                additional_headers=headers,
            )
        except TypeError:
            self._ws = await websockets.connect(self._ws_url, extra_headers=headers)
        logger.info("kalshi ws connected url=%s", self._ws_url)

    async def subscribe_orderbook(self, tickers: list[str] | None = None) -> None:
        targets = [t.upper() for t in (tickers or self._tickers)]
        batch_size = self._subscribe_batch_size
        for offset in range(0, len(targets), batch_size):
            batch = targets[offset : offset + batch_size]
            payload = {
                "id": self._msg_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": batch,
                },
            }
            self._msg_id += 1
            await self._ws.send(json.dumps(payload))
            logger.info(
                "kalshi ws subscribed orderbook batch=%d tickers=%s",
                len(batch),
                batch,
            )

    async def disconnect(self) -> None:
        if getattr(self, "_ws", None) is not None:
            await self._ws.close()
            logger.info("kalshi ws disconnected")

    def _apply_delta(self, ticker: str) -> OrderBookSnapshot | None:
        """Apply incremental delta when possible; fall back to cached book."""
        book = self._books.get(ticker.upper())
        if book is None:
            return None
        # Full delta book-keeping can be added later; return cached snapshot for now.
        return book

    async def stream(self) -> AsyncIterator[OrderBookSnapshot]:
        await self.connect()
        await self.subscribe_orderbook()
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                msg_type = data.get("type")
                if msg_type == "error":
                    logger.error("kalshi ws error: %s", data)
                    continue
                if msg_type == "orderbook_snapshot":
                    msg = data.get("msg") or {}
                    ticker = str(msg.get("market_ticker") or self._primary_ticker).upper()
                    book = snapshot_from_message(msg, ticker)
                    if book is not None:
                        self._books[book.ticker.upper()] = book
                        yield book
                elif msg_type == "orderbook_delta":
                    # Delta handling not implemented; avoid re-yielding stale books.
                    pass
        finally:
            await self.disconnect()
