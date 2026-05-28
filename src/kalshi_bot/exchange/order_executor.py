"""Execute trades when the strategy emits a sized signal."""

from __future__ import annotations

import logging
import time

import httpx

from kalshi_bot.config import Settings
from kalshi_bot.domain.models import ImbalanceSignal
from kalshi_bot.exchange.orders import PlacedOrder, place_limit_order
from kalshi_bot.risk.kelly import KellyAllocation

logger = logging.getLogger(__name__)


class OrderExecutor:
    """Places Kalshi orders with deduplication and cooldown guards."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._last_order_monotonic: dict[str, float] = {}
        self._session_keys: set[str] = set()
        self._write_permission_denied = False

    def _order_key(self, signal: ImbalanceSignal) -> str:
        return f"{signal.ticker.upper()}:{signal.side.value}"

    def remaining_session_slots(self) -> int:
        """How many more distinct orders this session may place."""
        return max(0, self._settings.max_orders_per_session - len(self._session_keys))

    def _cooldown_active(self, key: str) -> bool:
        last = self._last_order_monotonic.get(key)
        if last is None:
            return False
        elapsed = time.monotonic() - last
        return elapsed < self._settings.order_cooldown_sec

    async def maybe_execute(
        self,
        signal: ImbalanceSignal,
        allocation: KellyAllocation,
    ) -> PlacedOrder | None:
        """
        Place an order when trading is enabled and risk checks pass.

        Returns ``None`` when skipped (disabled, zero size, cooldown, duplicate).
        """
        if not self._settings.trading_enabled:
            return None

        if self._write_permission_denied:
            return None

        if allocation.contracts < 1:
            return None

        if len(self._session_keys) >= self._settings.max_orders_per_session:
            logger.debug(
                "skip order: session limit %d reached",
                self._settings.max_orders_per_session,
            )
            return None

        key = self._order_key(signal)
        if key in self._session_keys:
            logger.debug("skip order: already placed this session key=%s", key)
            return None

        if self._cooldown_active(key):
            logger.debug("skip order: cooldown active key=%s", key)
            return None

        try:
            placed = await place_limit_order(
                self._settings,
                signal,
                allocation,
                slippage_cents=self._settings.order_price_slippage_cents,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403 and "write" in exc.response.text.lower():
                self._write_permission_denied = True
                logger.error(
                    "Kalshi API key cannot place orders (read-only). "
                    "Create a new key at kalshi.com → Account → API Keys with "
                    "TRADING / WRITE permission, update KALSHI_API_KEY_ID and "
                    "KALSHI_PRIVATE_KEY_PATH in .env, then restart the bot."
                )
            else:
                logger.error(
                    "order failed ticker=%s status=%s",
                    signal.ticker,
                    exc.response.status_code,
                )
            return None

        self._session_keys.add(key)
        self._last_order_monotonic[key] = time.monotonic()
        return placed
