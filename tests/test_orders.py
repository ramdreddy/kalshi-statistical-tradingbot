from kalshi_bot.domain.models import ImbalanceSignal, Side
from kalshi_bot.exchange.orders import build_create_order_payload
from kalshi_bot.risk.kelly import KellyAllocation


def _allocation(contracts: int = 1) -> KellyAllocation:
    return KellyAllocation(
        contracts=contracts,
        true_probability=0.6,
        market_price_cents=7,
        bankroll_dollars=1.0,
        expected_value_cents=10.0,
        full_kelly_fraction=0.0,
        applied_kelly_fraction=0.0,
        capital_deployed_dollars=0.07,
    )


def test_build_yes_order_payload() -> None:
    signal = ImbalanceSignal(
        ticker="KXHIGHAUS-26MAY28-B86.5",
        side=Side.YES,
        edge_cents=5,
        confidence=0.5,
        reason="test",
        true_probability=0.15,
        market_price_cents=7,
    )
    body = build_create_order_payload(signal, _allocation(), slippage_cents=1)
    assert body["ticker"] == "KXHIGHAUS-26MAY28-B86.5"
    assert body["side"] == "yes"
    assert body["action"] == "buy"
    assert body["count"] == 1
    assert body["yes_price"] == 8
    assert "no_price" not in body


def test_build_no_order_payload() -> None:
    signal = ImbalanceSignal(
        ticker="KXHIGHAUS-26MAY28-B86.5",
        side=Side.NO,
        edge_cents=5,
        confidence=0.5,
        reason="test",
        true_probability=0.85,
        market_price_cents=6,
    )
    body = build_create_order_payload(signal, _allocation(2), slippage_cents=0)
    assert body["side"] == "no"
    assert body["no_price"] == 6
    assert body["count"] == 2
