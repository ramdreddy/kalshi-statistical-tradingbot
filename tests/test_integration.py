"""End-to-end smoke: analytics → risk sizing (no network)."""

from kalshi_bot.analytics import analyze_threshold
from kalshi_bot.domain.models import ImbalanceSignal, Side
from kalshi_bot.risk.sizing import size_signal


def test_analytics_to_fixed_bet_pipeline() -> None:
    analysis = analyze_threshold(
        threshold_f=90.0,
        forecast_mean_f=92.0,
        historical_std_f=4.0,
        market_price_cents=55,
    )
    assert analysis.expected_value_yes_cents > 0

    signal = ImbalanceSignal(
        ticker="TEST",
        side=Side.YES,
        edge_cents=10,
        confidence=0.5,
        reason="test",
        true_probability=analysis.probability_at_or_above,
        market_price_cents=analysis.market_price_cents,
    )
    allocation = size_signal(
        signal,
        bet_size_dollars=1.0,
        account_balance_dollars=11.0,
        min_account_balance_dollars=3.0,
    )
    assert allocation.contracts > 0
    assert allocation.capital_deployed_dollars <= 1.0
