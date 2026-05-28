"""
Position sizing via the fractional Kelly criterion for Kalshi YES contracts.

Isolated from strategy and analytics: consumes model probability and market
quotes, returns a whole-number contract count (or zero when risk gates fail).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kalshi_bot.analytics.weather_probability import expected_value_yes_cents

_SETTLE_CENTS = 100


@dataclass(frozen=True)
class KellyAllocation:
    """Sizing decision with audit fields."""

    contracts: int
    true_probability: float
    market_price_cents: int
    bankroll_dollars: float
    expected_value_cents: float
    full_kelly_fraction: float
    applied_kelly_fraction: float
    capital_deployed_dollars: float


def fractional_kelly_fraction(
    true_probability: float,
    market_price_cents: int,
    *,
    kelly_multiplier: float = 0.25,
    settle_cents: int = _SETTLE_CENTS,
) -> float:
    """
    Fraction of bankroll to allocate to YES, using fractional Kelly.

    Full Kelly for a binary YES at price ``c`` (decimal):

        f* = (p - c) / (1 - c)

    Applied fraction:

        f = kelly_multiplier * f*

    """
    if not 0.0 < true_probability < 1.0:
        raise ValueError("true_probability must be strictly between 0 and 1")
    if not 0 < market_price_cents < settle_cents:
        raise ValueError(f"market_price_cents must be between 0 and {settle_cents} (exclusive)")
    if not 0.0 < kelly_multiplier <= 1.0:
        raise ValueError("kelly_multiplier must be in (0, 1]")

    price = market_price_cents / settle_cents
    full_kelly = (true_probability - price) / (1.0 - price)
    return kelly_multiplier * full_kelly


def kelly_contract_allocation(
    true_probability: float,
    market_price_cents: int,
    bankroll_dollars: float,
    *,
    kelly_multiplier: float = 0.25,
    min_kelly_fraction: float = 0.01,
    settle_cents: int = _SETTLE_CENTS,
) -> KellyAllocation:
    """
    Compute how many YES contracts to buy under fractional Kelly sizing.

    Returns ``contracts=0`` when any gate fails:

    - Expected value per contract (cents) is not positive
    - Full Kelly fraction is not positive (no edge)
    - Applied Kelly fraction is below ``min_kelly_fraction`` (safety floor)
    - Bankroll cannot fund at least one contract at the computed size

    Parameters
    ----------
    true_probability:
        Model probability that the YES event occurs (0–1).
    market_price_cents:
        Current YES price in cents (1–99 typical).
    bankroll_dollars:
        Total risk capital in dollars.
    kelly_multiplier:
        Fractional Kelly scaler (e.g. 0.25 = quarter-Kelly).
    min_kelly_fraction:
        Minimum applied fraction of bankroll required to trade.
    """
    if bankroll_dollars <= 0:
        raise ValueError("bankroll_dollars must be positive")

    ev_cents = expected_value_yes_cents(
        true_probability, market_price_cents, settle_cents=settle_cents
    )
    price = market_price_cents / settle_cents
    full_kelly = (true_probability - price) / (1.0 - price)
    applied_kelly = kelly_multiplier * full_kelly

    zero = KellyAllocation(
        contracts=0,
        true_probability=true_probability,
        market_price_cents=market_price_cents,
        bankroll_dollars=bankroll_dollars,
        expected_value_cents=ev_cents,
        full_kelly_fraction=full_kelly,
        applied_kelly_fraction=applied_kelly,
        capital_deployed_dollars=0.0,
    )

    if ev_cents <= 0:
        return zero
    if full_kelly <= 0:
        return zero
    if applied_kelly < min_kelly_fraction:
        return zero

    cost_per_contract = market_price_cents / settle_cents
    bet_dollars = applied_kelly * bankroll_dollars
    contracts = int(math.floor(bet_dollars / cost_per_contract))

    if contracts < 1:
        return zero

    return KellyAllocation(
        contracts=contracts,
        true_probability=true_probability,
        market_price_cents=market_price_cents,
        bankroll_dollars=bankroll_dollars,
        expected_value_cents=ev_cents,
        full_kelly_fraction=full_kelly,
        applied_kelly_fraction=applied_kelly,
        capital_deployed_dollars=contracts * cost_per_contract,
    )
