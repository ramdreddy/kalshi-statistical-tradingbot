"""Place and track orders on Kalshi."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from kalshi_bot.config import Settings
from kalshi_bot.domain.models import ImbalanceSignal, Side
from kalshi_bot.exchange.kalshi_rest import kalshi_post_json
from kalshi_bot.risk.kelly import KellyAllocation

logger = logging.getLogger(__name__)

_ORDERS_PATH = "/portfolio/orders"


@dataclass(frozen=True)
class PlacedOrder:
    """Result of a submitted Kalshi order."""

    order_id: str
    client_order_id: str
    ticker: str
    side: Side
    count: int
    price_cents: int
    status: str
    raw: dict[str, Any]


def _limit_price_cents(
    signal: ImbalanceSignal,
    *,
    slippage_cents: int,
) -> int:
    """Pick a limit price for a buy (slightly through the book for fills)."""
    base = signal.market_price_cents
    price = base + max(0, slippage_cents)
    return max(1, min(99, price))


def build_create_order_payload(
    signal: ImbalanceSignal,
    allocation: KellyAllocation,
    *,
    client_order_id: str | None = None,
    slippage_cents: int = 1,
) -> dict[str, Any]:
    """Build ``POST /portfolio/orders`` JSON body."""
    if allocation.contracts < 1:
        raise ValueError("allocation.contracts must be >= 1")

    price_cents = _limit_price_cents(signal, slippage_cents=slippage_cents)
    payload: dict[str, Any] = {
        "ticker": signal.ticker.upper(),
        "action": "buy",
        "side": signal.side.value,
        "type": "limit",
        "count": allocation.contracts,
        "client_order_id": client_order_id or str(uuid.uuid4()),
    }
    if signal.side is Side.YES:
        payload["yes_price"] = price_cents
    else:
        payload["no_price"] = price_cents
    return payload


async def place_limit_order(
    settings: Settings,
    signal: ImbalanceSignal,
    allocation: KellyAllocation,
    *,
    client_order_id: str | None = None,
    slippage_cents: int = 1,
) -> PlacedOrder:
    """Submit a limit buy for YES or NO."""
    if settings.use_mock_exchange:
        price_cents = _limit_price_cents(signal, slippage_cents=slippage_cents)
        cid = client_order_id or str(uuid.uuid4())
        logger.info(
            "mock order ticker=%s side=%s count=%d price=%dc client_order_id=%s",
            signal.ticker,
            signal.side.value,
            allocation.contracts,
            price_cents,
            cid,
        )
        return PlacedOrder(
            order_id=f"mock-{cid[:8]}",
            client_order_id=cid,
            ticker=signal.ticker.upper(),
            side=signal.side,
            count=allocation.contracts,
            price_cents=price_cents,
            status="mock",
            raw={},
        )

    body = build_create_order_payload(
        signal,
        allocation,
        client_order_id=client_order_id,
        slippage_cents=slippage_cents,
    )
    try:
        response = await kalshi_post_json(settings, _ORDERS_PATH, json_body=body)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        logger.error(
            "kalshi create order failed status=%s body=%s",
            exc.response.status_code,
            detail,
        )
        raise

    order = response.get("order") or {}
    order_id = str(order.get("order_id") or "")
    if not order_id:
        raise ValueError(f"Unexpected create-order response: {response!r}")

    price_cents = body.get("yes_price") or body.get("no_price") or 0
    placed = PlacedOrder(
        order_id=order_id,
        client_order_id=str(order.get("client_order_id") or body["client_order_id"]),
        ticker=signal.ticker.upper(),
        side=signal.side,
        count=allocation.contracts,
        price_cents=int(price_cents),
        status=str(order.get("status") or "unknown"),
        raw=order,
    )
    logger.info(
        "order placed id=%s ticker=%s side=%s count=%d price=%dc status=%s",
        placed.order_id,
        placed.ticker,
        placed.side.value,
        placed.count,
        placed.price_cents,
        placed.status,
    )
    return placed
