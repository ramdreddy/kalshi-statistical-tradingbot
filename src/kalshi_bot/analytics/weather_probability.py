"""
Gaussian weather-threshold model for Kalshi temperature contracts.

Treats the forecast mean as the expected high (or target metric) and uses a
historical standard deviation to approximate P(temperature >= threshold).
"""

from __future__ import annotations

from dataclasses import dataclass

from scipy.stats import norm

# Kalshi binary contracts settle at $1.00 (100 cents) per YES share.
_SETTLE_CENTS = 100


@dataclass(frozen=True)
class ThresholdAnalysis:
    """Full model output for a single threshold vs. market quote."""

    threshold_f: float
    forecast_mean_f: float
    historical_std_f: float
    probability_at_or_above: float
    market_price_cents: int
    expected_value_yes_cents: float
    expected_value_no_cents: float
    edge_yes_cents: float
    edge_no_cents: float


def probability_at_or_above(
    threshold_f: float,
    forecast_mean_f: float,
    historical_std_f: float,
) -> float:
    """
    P(T >= threshold) under N(forecast_mean, historical_std^2).

    Uses the Gaussian survival function (1 - CDF).
    """
    if historical_std_f <= 0:
        raise ValueError("historical_std_f must be positive")
    return float(norm.sf(threshold_f, loc=forecast_mean_f, scale=historical_std_f))


def probability_at_or_below(
    threshold_f: float,
    forecast_mean_f: float,
    historical_std_f: float,
) -> float:
    """P(T <= threshold) under a Gaussian forecast-error model."""
    if historical_std_f <= 0:
        raise ValueError("historical_std_f must be positive")
    return float(norm.cdf(threshold_f, loc=forecast_mean_f, scale=historical_std_f))


def probability_in_bracket(
    low_f: float,
    high_f: float,
    forecast_mean_f: float,
    historical_std_f: float,
) -> float:
    """
    P(low <= T <= high) for inclusive integer °F brackets.

    Uses a continuity correction (+/- 0.5°F) on the Gaussian CDF.
    """
    if historical_std_f <= 0:
        raise ValueError("historical_std_f must be positive")
    if low_f > high_f:
        raise ValueError("low_f must be <= high_f")
    lower = low_f - 0.5
    upper = high_f + 0.5
    return float(
        norm.cdf(upper, loc=forecast_mean_f, scale=historical_std_f)
        - norm.cdf(lower, loc=forecast_mean_f, scale=historical_std_f)
    )


def expected_value_yes_cents(
    true_probability: float,
    market_price_cents: int,
    *,
    settle_cents: int = _SETTLE_CENTS,
) -> float:
    """
    EV in cents of buying one YES contract at ``market_price_cents``.

    EV = p * (settle - price) - (1 - p) * price
       = p * settle - price
    """
    if not 0.0 <= true_probability <= 1.0:
        raise ValueError("true_probability must be between 0 and 1")
    if not 0 <= market_price_cents <= settle_cents:
        raise ValueError(f"market_price_cents must be between 0 and {settle_cents}")
    return true_probability * settle_cents - market_price_cents


def expected_value_no_cents(
    true_probability: float,
    market_price_cents: int,
    *,
    settle_cents: int = _SETTLE_CENTS,
) -> float:
    """EV in cents of buying one NO contract (YES implied at ``market_price_cents``)."""
    no_price = settle_cents - market_price_cents
    p_no = 1.0 - true_probability
    return p_no * settle_cents - no_price


def analyze_threshold(
    threshold_f: float,
    forecast_mean_f: float,
    historical_std_f: float,
    market_price_cents: int,
) -> ThresholdAnalysis:
    """
    Compute model probability and YES/NO expected values vs. a market quote.

    Parameters
    ----------
    threshold_f:
        Contract strike, e.g. 90.0 for "high temp >= 90°F".
    forecast_mean_f:
        Point forecast for the relevant metric (same units as threshold).
    historical_std_f:
        Historical standard deviation of forecast errors (same units).
    market_price_cents:
        Current YES mid or ask in cents (1–99 typical).
    """
    p = probability_at_or_above(threshold_f, forecast_mean_f, historical_std_f)
    ev_yes = expected_value_yes_cents(p, market_price_cents)
    ev_no = expected_value_no_cents(p, market_price_cents)
    return ThresholdAnalysis(
        threshold_f=threshold_f,
        forecast_mean_f=forecast_mean_f,
        historical_std_f=historical_std_f,
        probability_at_or_above=p,
        market_price_cents=market_price_cents,
        expected_value_yes_cents=ev_yes,
        expected_value_no_cents=ev_no,
        edge_yes_cents=ev_yes,
        edge_no_cents=ev_no,
    )
