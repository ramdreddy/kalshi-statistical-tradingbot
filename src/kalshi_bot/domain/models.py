"""Domain models shared across feeds, exchange, and strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Side(str, Enum):
    YES = "yes"
    NO = "no"


@dataclass(frozen=True)
class OrderBookLevel:
    price_cents: int
    quantity: int


@dataclass(frozen=True)
class OrderBookSnapshot:
    ticker: str
    yes_bids: tuple[OrderBookLevel, ...]
    yes_asks: tuple[OrderBookLevel, ...]
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def best_bid_cents(self) -> int | None:
        return self.yes_bids[0].price_cents if self.yes_bids else None

    @property
    def best_ask_cents(self) -> int | None:
        return self.yes_asks[0].price_cents if self.yes_asks else None

    @property
    def spread_cents(self) -> int | None:
        if self.best_bid_cents is None or self.best_ask_cents is None:
            return None
        return self.best_ask_cents - self.best_bid_cents


@dataclass(frozen=True)
class WeatherMetrics:
    location: str
    temperature_f: float
    humidity_pct: float
    wind_speed_mph: float
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ImbalanceSignal:
    ticker: str
    side: Side
    edge_cents: int
    confidence: float
    reason: str
