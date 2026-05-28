from kalshi_bot.domain.models import ImbalanceSignal, Side
from kalshi_bot.risk.sizing import size_signal


def _signal(
    *,
    side: Side = Side.YES,
    true_probability: float = 0.7,
    market_price_cents: int = 50,
) -> ImbalanceSignal:
    return ImbalanceSignal(
        ticker="TEST",
        side=side,
        edge_cents=10,
        confidence=0.5,
        reason="test",
        true_probability=true_probability,
        market_price_cents=market_price_cents,
    )


def test_blocks_when_account_below_minimum() -> None:
    result = size_signal(
        _signal(),
        bet_size_dollars=1.0,
        account_balance_dollars=2.99,
        min_account_balance_dollars=3.0,
    )
    assert result.contracts == 0


def test_blocks_when_account_cannot_cover_bet() -> None:
    result = size_signal(
        _signal(),
        bet_size_dollars=1.0,
        account_balance_dollars=0.75,
        min_account_balance_dollars=0.5,
    )
    assert result.contracts == 0


def test_one_dollar_bet_at_fifty_cents() -> None:
    # $1 / $0.50 per contract = 2 contracts = $1.00 deployed
    result = size_signal(
        _signal(true_probability=0.7, market_price_cents=50),
        bet_size_dollars=1.0,
        account_balance_dollars=11.0,
        min_account_balance_dollars=3.0,
    )
    assert result.contracts == 2
    assert result.capital_deployed_dollars == 1.0


def test_one_dollar_bet_at_ninety_cents() -> None:
    # $1 / $0.90 = 1 contract, $0.90 deployed (max whole contracts within budget)
    result = size_signal(
        _signal(true_probability=0.95, market_price_cents=90),
        bet_size_dollars=1.0,
        account_balance_dollars=11.0,
        min_account_balance_dollars=3.0,
    )
    assert result.contracts == 1
    assert result.capital_deployed_dollars == 0.9


def test_blocks_negative_ev() -> None:
    result = size_signal(
        _signal(true_probability=0.4, market_price_cents=50),
        bet_size_dollars=1.0,
        account_balance_dollars=11.0,
        min_account_balance_dollars=3.0,
    )
    assert result.contracts == 0


def test_caps_contracts_per_order() -> None:
    # $1 / 3c = 33 contracts without cap; limited to 10
    result = size_signal(
        _signal(true_probability=0.3, market_price_cents=3),
        bet_size_dollars=1.0,
        account_balance_dollars=11.0,
        min_account_balance_dollars=3.0,
        max_contracts_per_order=10,
    )
    assert result.contracts == 10
    assert result.capital_deployed_dollars == 0.3
