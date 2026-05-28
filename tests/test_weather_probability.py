import math

import pytest

from kalshi_bot.analytics.weather_probability import (
    analyze_threshold,
    expected_value_yes_cents,
    probability_at_or_above,
    probability_in_bracket,
)


def test_probability_at_or_above_symmetric_at_mean() -> None:
    p = probability_at_or_above(90.0, forecast_mean_f=90.0, historical_std_f=5.0)
    assert math.isclose(p, 0.5, abs_tol=1e-6)


def test_probability_in_bracket_peaks_near_mean() -> None:
    p_center = probability_in_bracket(79, 80, 79.5, 2.0)
    p_far = probability_in_bracket(79, 80, 95.0, 2.0)
    assert p_center > p_far


def test_probability_increases_when_mean_above_threshold() -> None:
    p_low = probability_at_or_above(90.0, 85.0, 5.0)
    p_high = probability_at_or_above(90.0, 95.0, 5.0)
    assert p_high > p_low
    assert p_low < 0.5 < p_high


def test_invalid_std_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        probability_at_or_above(90.0, 90.0, 0.0)


def test_expected_value_yes_at_fair_price() -> None:
    # p=0.6, price=60c -> EV = 0.6*100 - 60 = 0
    assert expected_value_yes_cents(0.6, 60) == pytest.approx(0.0)


def test_expected_value_yes_positive_edge() -> None:
    # p=0.7, price=60c -> EV = 70 - 60 = 10c
    assert expected_value_yes_cents(0.7, 60) == pytest.approx(10.0)


def test_analyze_threshold_returns_full_result() -> None:
    result = analyze_threshold(
        threshold_f=90.0,
        forecast_mean_f=92.0,
        historical_std_f=4.0,
        market_price_cents=55,
    )
    assert result.probability_at_or_above > 0.5
    assert result.expected_value_yes_cents == pytest.approx(
        result.probability_at_or_above * 100 - 55,
        rel=1e-6,
    )
