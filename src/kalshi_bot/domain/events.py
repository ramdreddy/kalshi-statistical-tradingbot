"""Event envelope for the async event bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    ORDERBOOK = "orderbook"
    WEATHER = "weather"
    SIGNAL = "signal"
    SHUTDOWN = "shutdown"


@dataclass(frozen=True)
class Event:
    type: EventType
    payload: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
