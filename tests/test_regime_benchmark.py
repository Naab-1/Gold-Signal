"""Tests for the regime-classifier benchmark comparison (STRATEGY
RESEARCH AND REPLACEMENT program, Phase 5) -- verifies the classifier's
trend/range calls agree with ADX and its high/low-volatility calls
agree with Bollinger Band width, two independent, differently-derived
indicators never used to build the classifier itself.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from goldsignal.analysis.regime import load_regime_classifier_config
from goldsignal.analysis.regime_benchmark import compare_regime_to_benchmark
from goldsignal.models.candle import Candle

START = datetime(2023, 1, 1, tzinfo=UTC)


def _candle(i, o, h, low, c):
    return Candle(
        timestamp=START + timedelta(minutes=15 * i), open=o, high=h, low=low, close=c, volume=1
    )


def _mixed_regime_series(seed=3):
    """Alternating calm/volatile blocks with drifting and flat stretches,
    so both the trend/range axis and the volatility axis get exercised
    with a genuine regime shift to compare against -- a plain stationary
    random walk (e.g. MockDataProvider) never shifts its own volatility,
    so it can't exercise the volatility-benchmark comparison at all.
    """
    rng = random.Random(seed)
    candles = []
    price = 2400.0
    vol_schedule = [0.3, 0.3, 4.0, 4.0, 0.3, 4.0, 0.3, 4.0] * 3
    i = 0
    for vol in vol_schedule:
        for _ in range(200):
            o = price
            cl = price + rng.gauss(0, vol)
            h = max(o, cl) + abs(rng.gauss(0, vol / 3))
            low = min(o, cl) - abs(rng.gauss(0, vol / 3))
            candles.append(_candle(i, o, h, low, cl))
            price = cl
            i += 1
    return candles


def test_benchmark_reports_high_trend_range_agreement_with_adx():
    config = load_regime_classifier_config({})
    candles = _mixed_regime_series()
    report = compare_regime_to_benchmark(candles, config)
    assert report.trend_range_compared_count > 100
    assert report.trend_range_agreement is not None
    assert report.trend_range_agreement > 0.7


def test_benchmark_reports_high_volatility_agreement_with_bollinger_width():
    config = load_regime_classifier_config({})
    candles = _mixed_regime_series()
    report = compare_regime_to_benchmark(candles, config)
    assert report.volatility_compared_count > 100
    assert report.volatility_agreement is not None
    assert report.volatility_agreement > 0.7


def test_benchmark_regime_counts_cover_multiple_regimes():
    config = load_regime_classifier_config({})
    candles = _mixed_regime_series()
    report = compare_regime_to_benchmark(candles, config)
    assert len(report.regime_counts) >= 3


def test_benchmark_returns_none_agreement_when_nothing_comparable():
    config = load_regime_classifier_config({})
    # Too short for either the classifier or ADX/Bollinger to produce any
    # values at all.
    candles = [_candle(i, 100, 101, 99, 100.5) for i in range(5)]
    report = compare_regime_to_benchmark(candles, config)
    assert report.trend_range_agreement is None
    assert report.trend_range_compared_count == 0
    assert report.volatility_agreement is None
    assert report.volatility_compared_count == 0
