"""Tests for the generic single-candidate walk harness."""

from __future__ import annotations

from datetime import UTC, datetime

from goldsignal.analysis.candidate_walk import run_candidate_dev_validation, walk_candidate
from goldsignal.config import load_trend_pullback_mode_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.signal import StrategyMode
from goldsignal.strategy.candidates.trend_pullback import (
    TrendPullbackStrategy,
    load_trend_pullback_config,
)

START = datetime(2026, 1, 1, tzinfo=UTC)

_LOOSE_FAMILY_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "MIN_NET_REWARD_R": "0.1",
    "TREND_STRENGTH_ATR_MULTIPLE": "0.1",
}


def _configs():
    mode_config = load_trend_pullback_mode_config(
        {
            "GOLDSIGNAL_TRENDPULLBACK_COOLDOWN_MINUTES": "0",
            "GOLDSIGNAL_TRENDPULLBACK_MAX_SIGNALS_PER_SESSION": "10000",
        }
    )
    family_config = load_trend_pullback_config(
        {f"GOLDSIGNAL_TRENDPULLBACK_{k}": v for k, v in _LOOSE_FAMILY_OVERRIDES.items()}
    )
    return mode_config, family_config


def _candles(mode_config):
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 3000
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    return entry, confirm


def test_walk_candidate_produces_trades_and_grade_counts():
    mode_config, family_config = _configs()
    entry, confirm = _candles(mode_config)
    strategy = TrendPullbackStrategy(mode_config, family_config, "XAUUSD")

    result = walk_candidate(strategy, entry, confirm)

    assert len(result.trades) > 0
    assert result.grade_counts["BUY"] + result.grade_counts["SELL"] == len(result.trades)
    assert result.total_days > 0
    assert 0 <= result.zero_signal_days <= result.total_days


def test_run_candidate_dev_validation_never_mixes_splits():
    mode_config, family_config = _configs()
    entry, confirm = _candles(mode_config)
    strategy = TrendPullbackStrategy(mode_config, family_config, "XAUUSD")

    summary = run_candidate_dev_validation(strategy, StrategyMode.TREND_PULLBACK, entry, confirm)

    assert summary.development.split_label == "development"
    assert summary.validation.split_label == "validation"
    # Two distinct BacktestSummary objects -- never one blended result.
    assert summary.development is not summary.validation
    total_actionable = summary.grade_counts.get("BUY", 0) + summary.grade_counts.get("SELL", 0)
    assert summary.development.total_trades + summary.validation.total_trades <= total_actionable


def test_no_lookahead_truncated_and_full_walks_agree():
    mode_config, family_config = _configs()
    entry, confirm = _candles(mode_config)
    strategy = TrendPullbackStrategy(mode_config, family_config, "XAUUSD")

    cut = 1500
    entry_truncated = entry[:cut]

    full_result = walk_candidate(strategy, entry, confirm)
    truncated_result = walk_candidate(strategy, entry_truncated, confirm)

    assert len(truncated_result.trades) > 0, "expected at least one trade in the truncated window"
    full_by_id = {
        t.signal_id: t for t in full_result.trades if t.fill_timestamp <= entry[cut - 1].timestamp
    }
    for t in truncated_result.trades:
        match = full_by_id.get(t.signal_id)
        assert match is not None, "a truncated-run trade is missing from the full run"
        assert match.fill_price == t.fill_price
        assert match.direction == t.direction
        assert match.initial_stop_loss == t.initial_stop_loss
