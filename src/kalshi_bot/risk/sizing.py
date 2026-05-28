"""Position sizing: fixed dollar amount per bet with account safety gates."""

from __future__ import annotations

import math

from kalshi_bot.analytics.weather_probability import expected_value_yes_cents
from kalshi_bot.domain.models import ImbalanceSignal, Side
from kalshi_bot.risk.kelly import KellyAllocation

_SETTLE_CENTS = 100


def size_signal(
    signal: ImbalanceSignal,
    *,
    bet_size_dollars: float,
    account_balance_dollars: float,
    min_account_balance_dollars: float,
    max_contracts_per_order: int = 10,
) -> KellyAllocation:
    """
    Size each trade to deploy up to ``bet_size_dollars`` (default $1).

    Contract count is capped at ``max_contracts_per_order`` (default 10) even when
  a cheap YES price would allow more shares within the dollar budget.

    Returns zero contracts when:
    - Account balance is below ``min_account_balance_dollars`` ($3 default)
    - Account cannot cover the bet size
    - Expected value is not positive
    - Not enough capital to buy at least one contract
    """
    probability = signal.true_probability
    price_cents = signal.market_price_cents
    if signal.side is Side.NO:
        probability = 1.0 - signal.true_probability
        price_cents = 100 - signal.market_price_cents

    ev_cents = expected_value_yes_cents(probability, price_cents)
    cost_per_contract = price_cents / _SETTLE_CENTS

    zero = KellyAllocation(
        contracts=0,
        true_probability=probability,
        market_price_cents=price_cents,
        bankroll_dollars=bet_size_dollars,
        expected_value_cents=ev_cents,
        full_kelly_fraction=0.0,
        applied_kelly_fraction=0.0,
        capital_deployed_dollars=0.0,
    )

    if account_balance_dollars < min_account_balance_dollars:
        return zero
    if account_balance_dollars < bet_size_dollars:
        return zero
    if ev_cents <= 0:
        return zero
    if cost_per_contract <= 0:
        return zero

    contracts = int(math.floor(bet_size_dollars / cost_per_contract))
    if max_contracts_per_order > 0:
        contracts = min(contracts, max_contracts_per_order)
    if contracts < 1:
        return zero

    capital = contracts * cost_per_contract
    return KellyAllocation(
        contracts=contracts,
        true_probability=probability,
        market_price_cents=price_cents,
        bankroll_dollars=bet_size_dollars,
        expected_value_cents=ev_cents,
        full_kelly_fraction=0.0,
        applied_kelly_fraction=0.0,
        capital_deployed_dollars=capital,
    )
