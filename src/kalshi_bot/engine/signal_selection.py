"""Rank trade candidates so the engine can prefer the largest edges."""

from __future__ import annotations

from dataclasses import dataclass

from kalshi_bot.domain.models import ImbalanceSignal
from kalshi_bot.risk.kelly import KellyAllocation


@dataclass(frozen=True)
class SizedSignal:
    """Strategy signal with a sized allocation ready for execution."""

    signal: ImbalanceSignal
    allocation: KellyAllocation


def rank_signals_by_edge(candidates: list[SizedSignal]) -> list[SizedSignal]:
    """Sort by ``edge_cents`` descending (stable for equal edges)."""
    return sorted(candidates, key=lambda item: item.signal.edge_cents, reverse=True)
