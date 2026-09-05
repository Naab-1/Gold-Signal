"""Tests for the performance-evaluation framework (STRATEGY RESEARCH AND
REPLACEMENT program, Phase 7): regime tagging, session grouping, and an
end-to-end run with a real Phase 4 candidate against synthetic data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from goldsignal.analysis.performance_evaluation import (
    evaluate_candidate_performance,
    group_trades_by_session,
    regime_at_or_before,
    summarize_groups,
    tag_trades_with_regime,
)
from goldsignal.analysis.regime import MarketRegime, load_regime_classifier_config
from goldsignal.backtest.models import BacktestTrade
from goldsignal.config import load_trend_pullback_mode_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.candidates.trend_pullback import (
    TrendPullbackStrategy,
    load_trend_pullback_config,
)
from goldsignal.strategy.trade_management import TradeManagementPreset

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, o=100.0, h=101.0, low=99.0, c=100.0):
    return Candle(timestamp=START + timedelta(hours=i), open=o, high=h, low=low, close=c, volume=1)


def _trade(signal_ts, realized_r=1.0):
    return BacktestTrade(
        signal_id=f"t-{signal_ts.isoformat()}",
        strategy_mode=StrategyMode.TREND_PULLBACK,
        strategy_version="test_v1",
        trade_management_preset=TradeManagementPreset.BALANCED,
        direction=SignalDirection.BUY,
        signal_timestamp=signal_ts,
        fill_timestamp=signal_ts,
        fill_price=100.0,
        initial_stop_loss=99.0,
        risk=1.0,
        realized_r=realized_r,
    )


# --- regime_at_or_before -------------------------------------------------------


def test_regime_at_or_before_returns_none_before_first_candle():
    regime_candles = [_candle(0), _candle(1), _candle(2)]
    regime_series = [MarketRegime.RANGING, MarketRegime.TRENDING, MarketRegime.TRENDING]
    query = START - timedelta(minutes=1)
    assert regime_at_or_before(query, regime_candles, regime_series) is None


def test_regime_at_or_before_returns_latest_at_or_before_query():
    regime_candles = [_candle(0), _candle(1), _candle(2)]
    regime_series = [MarketRegime.RANGING, MarketRegime.TRENDING, MarketRegime.HIGH_VOLATILITY]
    # exactly at candle 1's timestamp
    assert regime_at_or_before(_candle(1).timestamp, regime_candles, regime_series) == (
        MarketRegime.TRENDING
    )
    # between candle 1 and candle 2 -- should still read candle 1's regime
    between = _candle(1).timestamp + timedelta(minutes=30)
    assert regime_at_or_before(between, regime_candles, regime_series) == MarketRegime.TRENDING
    # at/after the last candle -- reads the last regime
    after = _candle(2).timestamp + timedelta(hours=5)
    assert regime_at_or_before(after, regime_candles, regime_series) == (
        MarketRegime.HIGH_VOLATILITY
    )


def test_regime_at_or_before_returns_none_when_series_value_is_none():
    regime_candles = [_candle(0), _candle(1)]
    regime_series = [None, MarketRegime.RANGING]
    assert regime_at_or_before(_candle(0).timestamp, regime_candles, regime_series) is None


# --- tag_trades_with_regime -----------------------------------------------------


def test_tag_trades_with_regime_groups_by_classified_regime():
    regime_candles = [_candle(0), _candle(1), _candle(2)]
    regime_series = [MarketRegime.RANGING, MarketRegime.TRENDING, MarketRegime.TRENDING]
    trades = [
        _trade(_candle(0).timestamp),
        _trade(_candle(1).timestamp + timedelta(minutes=10)),
        _trade(_candle(2).timestamp + timedelta(minutes=10)),
    ]
    groups = tag_trades_with_regime(trades, regime_candles, regime_series)
    assert set(groups.keys()) == {"RANGING", "TRENDING"}
    assert len(groups["RANGING"]) == 1
    assert len(groups["TRENDING"]) == 2


def test_tag_trades_with_regime_uses_unknown_bucket_for_unclassifiable_trades():
    regime_candles = [_candle(5)]
    regime_series = [MarketRegime.TRENDING]
    trades = [_trade(_candle(0).timestamp)]  # before the only regime candle
    groups = tag_trades_with_regime(trades, regime_candles, regime_series)
    assert set(groups.keys()) == {"UNKNOWN"}


# --- group_trades_by_session / summarize_groups ---------------------------------


def test_summarize_groups_matches_compute_summary_per_group():
    from goldsignal.backtest.metrics import compute_summary

    trades = [_trade(START, realized_r=1.0), _trade(START, realized_r=-1.0)]
    groups = {"all": trades}
    summaries = summarize_groups(
        groups,
        strategy_mode=StrategyMode.TREND_PULLBACK,
        preset=TradeManagementPreset.BALANCED,
        split_label="development",
    )
    expected = compute_summary(
        trades,
        strategy_mode=StrategyMode.TREND_PULLBACK,
        preset=TradeManagementPreset.BALANCED,
        split_label="development",
    )
    assert summaries["all"] == expected


def test_group_trades_by_session_covers_every_trade_exactly_once():
    trades = [_trade(START + timedelta(hours=h)) for h in range(0, 48, 3)]
    groups = group_trades_by_session(trades)
    assert sum(len(g) for g in groups.values()) == len(trades)


# --- evaluate_candidate_performance: end-to-end with a real candidate -----------


def test_evaluate_candidate_performance_never_exceeds_total_trade_count():
    mode_config = load_trend_pullback_mode_config(
        {
            "GOLDSIGNAL_TRENDPULLBACK_COOLDOWN_MINUTES": "0",
            "GOLDSIGNAL_TRENDPULLBACK_MAX_SIGNALS_PER_SESSION": "10000",
        }
    )
    family_config = load_trend_pullback_config(
        {
            "GOLDSIGNAL_TRENDPULLBACK_COOLDOWN_MINUTES": "0",
            "GOLDSIGNAL_TRENDPULLBACK_MAX_SIGNALS_PER_SESSION": "10000",
            "GOLDSIGNAL_TRENDPULLBACK_MIN_NET_REWARD_R": "0.1",
        }
    )
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 4000
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)

    strategy = TrendPullbackStrategy(mode_config, family_config, "XAUUSD")
    regime_config = load_regime_classifier_config({})

    evaluation = evaluate_candidate_performance(
        family="trend_pullback",
        instrument="XAUUSD",
        strategy=strategy,
        mode=StrategyMode.TREND_PULLBACK,
        entry_candles=entry,
        confirmation_candles=confirm,
        regime_candles=confirm,  # use the confirmation timeframe as the shared regime reference
        regime_config=regime_config,
    )

    assert evaluation.family == "trend_pullback"
    total_dev = evaluation.development.total_trades
    total_val = evaluation.validation.total_trades

    # Regime and session buckets must partition each split exactly --
    # no trade counted twice, none silently dropped.
    assert sum(s.total_trades for s in evaluation.development_by_regime.values()) == total_dev
    assert sum(s.total_trades for s in evaluation.validation_by_regime.values()) == total_val
    assert sum(s.total_trades for s in evaluation.development_by_session.values()) == total_dev
    assert sum(s.total_trades for s in evaluation.validation_by_session.values()) == total_val
