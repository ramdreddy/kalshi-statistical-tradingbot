"""Kalshi weather market metadata discovered from the exchange."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BracketStrikeType(str, Enum):
    """How a weather contract settles relative to the official daily high."""

    BETWEEN = "between"
    GREATER_OR_EQUAL = "greater_or_equal"
    LESS_OR_EQUAL = "less_or_equal"
    GREATER = "greater"
    LESS = "less"


@dataclass(frozen=True)
class WeatherBracketMarket:
    """One tradeable Kalshi bracket (or threshold) within a daily high event."""

    ticker: str
    event_ticker: str
    series_ticker: str
    title: str
    strike_type: BracketStrikeType
    floor_f: Optional[float] = None
    cap_f: Optional[float] = None
    subtitle: str = ""

    def describe_bracket(self) -> str:
        if self.strike_type == BracketStrikeType.BETWEEN:
            return f"{self.floor_f:.0f}–{self.cap_f:.0f}°F"
        if self.strike_type == BracketStrikeType.LESS_OR_EQUAL and self.cap_f is not None:
            return f"≤{self.cap_f:.0f}°F"
        if self.strike_type in (BracketStrikeType.GREATER_OR_EQUAL, BracketStrikeType.GREATER):
            return f"≥{self.floor_f:.0f}°F"
        return self.title
