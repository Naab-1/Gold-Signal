"""Tests for the market-regime classifier (STRATEGY RESEARCH AND
REPLACEMENT program, Phase 5). Each of the five regimes is exercised
with an engineered synthetic series that has a known, intended
ground-truth regime -- more rigorous than real data for validating a
classifier, since real market data has no agreed-upon ground-truth
regime label to check against.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.analysis.regime import (
    MarketRegime,
    classify_regime,
    classify_regime_series,
    load_regime_classifier_config,
)
from goldsignal.config import ConfigError
from goldsignal.models.candle import Candle

START = datetime(2023, 1, 1, tzinfo=UTC)


def _candle(i, o, h, low, c):
    return Candle(
        timestamp=START + timedelta(minutes=15 * i), open=o, high=h, low=low, close=c, volume=1
    )


def _uptrend_candles(n=160, step=0.6):
    return [
        _candle(i, 100 + i * step, 101 + i * step, 99 + i * step, 100.5 + i * step)
        for i in range(n)
    ]


def _range_candles(n=160):
    candles = []
    for i in range(n):
        base = 100 + (0.5 if i % 2 == 0 else -0.5)
        candles.append(_candle(i, base, base + 0.3, base - 0.3, base + 0.05))
    return candles


def _calm_then_spike_candles(n_calm=150, n_spike=20, seed=1):
    rng = random.Random(seed)
    candles = []
    price = 100.0
    for i in range(n_calm):
        o = price
        cl = price + rng.gauss(0, 0.05)
        h = max(o, cl) + 0.05
        low = min(o, cl) - 0.05
        candles.append(_candle(i, o, h, low, cl))
        price = cl
    for i in range(n_calm, n_calm + n_spike):
        o = price
        cl = price + rng.gauss(0, 3.0)
        h = max(o, cl) + 1.0
        low = min(o, cl) - 1.0
        candles.append(_candle(i, o, h, low, cl))
        price = cl
    return candles


def _normal_then_calm_candles(n_normal=150, n_calm=20, seed=1):
    rng = random.Random(seed)
    candles = []
    price = 100.0
    for i in range(n_normal):
        o = price
        cl = price + rng.gauss(0, 0.3)
        h = max(o, cl) + 0.1
        low = min(o, cl) - 0.1
        candles.append(_candle(i, o, h, low, cl))
        price = cl
    for i in range(n_normal, n_normal + n_calm):
        o = price
        cl = price + rng.gauss(0, 0.02)
        h = max(o, cl) + 0.01
        low = min(o, cl) - 0.01
        candles.append(_candle(i, o, h, low, cl))
        price = cl
    return candles


# --- Config -----------------------------------------------------------------


def test_config_defaults_load():
    config = load_regime_classifier_config({})
    assert config.ema_fast_period == 20
    assert config.ema_slow_period == 50
    assert config.trend_strength_atr_multiple == 1.0
    assert config.range_strength_atr_multiple == 0.5


def test_config_rejects_slow_ema_not_greater_than_fast():
    with pytest.raises(ConfigError):
        load_regime_classifier_config(
            {
                "GOLDSIGNAL_REGIMECLASSIFIER_EMA_FAST_PERIOD": "20",
                "GOLDSIGNAL_REGIMECLASSIFIER_EMA_SLOW_PERIOD": "20",
            }
        )


def test_config_rejects_trend_threshold_not_greater_than_range_threshold():
    with pytest.raises(ConfigError):
        load_regime_classifier_config(
            {
                "GOLDSIGNAL_REGIMECLASSIFIER_TREND_STRENGTH_ATR_MULTIPLE": "0.5",
                "GOLDSIGNAL_REGIMECLASSIFIER_RANGE_STRENGTH_ATR_MULTIPLE": "0.5",
            }
        )


def test_config_rejects_high_volatility_ratio_not_above_one():
    with pytest.raises(ConfigError):
        load_regime_classifier_config(
            {"GOLDSIGNAL_REGIMECLASSIFIER_HIGH_VOLATILITY_ATR_RATIO": "1.0"}
        )


def test_config_rejects_low_volatility_ratio_out_of_range():
    with pytest.raises(ConfigError):
        load_regime_classifier_config(
            {"GOLDSIGNAL_REGIMECLASSIFIER_LOW_VOLATILITY_ATR_RATIO": "1.0"}
        )


# --- classify_regime: one engineered scenario per regime ---------------------


def test_classifies_clean_uptrend_as_trending():
    config = load_regime_classifier_config({})
    assert classify_regime(_uptrend_candles(), config) == MarketRegime.TRENDING


def test_classifies_clean_downtrend_as_trending():
    config = load_regime_classifier_config({})
    down = [
        _candle(i, 200 - i * 0.6, 201 - i * 0.6, 199 - i * 0.6, 200.5 - i * 0.6) for i in range(160)
    ]
    assert classify_regime(down, config) == MarketRegime.TRENDING


def test_classifies_flat_oscillation_as_ranging():
    config = load_regime_classifier_config({})
    assert classify_regime(_range_candles(), config) == MarketRegime.RANGING


def test_classifies_sudden_spike_as_high_volatility():
    config = load_regime_classifier_config({})
    assert classify_regime(_calm_then_spike_candles(), config) == MarketRegime.HIGH_VOLATILITY


def test_classifies_sudden_calm_as_low_volatility():
    config = load_regime_classifier_config({})
    assert classify_regime(_normal_then_calm_candles(), config) == MarketRegime.LOW_VOLATILITY


def test_classifies_ambiguous_middle_ground_as_uncertain():
    config = load_regime_classifier_config({})
    # A mild drift -- not flat enough for RANGING, not strong enough for
    # TRENDING under the default thresholds' gray-zone gap.
    mild = [
        _candle(i, 100 + i * 0.12, 101 + i * 0.12, 99 + i * 0.12, 100.3 + i * 0.12)
        for i in range(160)
    ]
    assert classify_regime(mild, config) == MarketRegime.UNCERTAIN


def test_returns_none_for_insufficient_history():
    config = load_regime_classifier_config({})
    assert classify_regime(_uptrend_candles(n=10), config) is None


def test_returns_none_for_empty_candles():
    config = load_regime_classifier_config({})
    assert classify_regime([], config) is None


# --- classify_regime_series ---------------------------------------------------


def test_series_matches_single_call_at_every_valid_index():
    config = load_regime_classifier_config({})
    candles = _uptrend_candles()
    series = classify_regime_series(candles, config)
    assert len(series) == len(candles)
    # No-lookahead proof: classifying a truncated prefix must match the
    # series value at that same index -- classification at index i must
    # never depend on candles after i.
    for i in (50, 100, 159):
        assert classify_regime(candles[: i + 1], config) == series[i]


def test_series_empty_for_empty_candles():
    config = load_regime_classifier_config({})
    assert classify_regime_series([], config) == []
