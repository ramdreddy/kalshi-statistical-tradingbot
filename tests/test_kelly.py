import pytest

from kalshi_bot.risk.kelly import (
    fractional_kelly_fraction,
    kelly_contract_allocation,
)


def test_fractional_kelly_quarter_kelly_example() -> None:
    # p=0.6, price=50c -> full Kelly = (0.6-0.5)/0.5 = 0.2, quarter = 0.05
    assert fractional_kelly_fraction(0.6, 50, kelly_multiplier=0.25) == pytest.approx(0.05)


def test_allocation_zero_when_ev_negative() -> None:
    result = kelly_contract_allocation(0.45, 50, 10_000.0)
    assert result.contracts == 0
    assert result.expected_value_cents < 0


def test_allocation_zero_when_below_safety_threshold() -> None:
    # Tiny edge: p=0.51, c=50 -> full kelly = 0.02, quarter = 0.005 < 0.01 min
    result = kelly_contract_allocation(
        0.51,
        50,
        10_000.0,
        kelly_multiplier=0.25,
        min_kelly_fraction=0.01,
    )
    assert result.contracts == 0


def test_allocation_positive_contracts() -> None:
    # p=0.7, c=50, bankroll 1000, quarter kelly -> ~10% of bankroll, ~200 contracts at 50c
    result = kelly_contract_allocation(0.7, 50, 1_000.0, kelly_multiplier=0.25)
    assert result.contracts >= 199
    assert result.capital_deployed_dollars == pytest.approx(100.0, abs=1.0)
    assert result.expected_value_cents > 0


def test_allocation_zero_when_bankroll_too_small_for_one_contract() -> None:
    result = kelly_contract_allocation(0.7, 50, 1.0, kelly_multiplier=0.25)
    assert result.contracts == 0
