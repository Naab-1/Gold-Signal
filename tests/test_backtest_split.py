from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.backtest.models import BacktestTrade
from goldsignal.backtest.split import (
    split_cutoff_timestamp,
    split_cutoff_timestamps,
    split_trades,
    split_trades_three_way,
)
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.trade_management import TradeManagementPreset

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i):
    return Candle(
        timestamp=START + timedelta(hours=i), open=100, high=101, low=99, close=100, volume=1
    )


def _trade(signal_timestamp):
    return BacktestTrade(
        signal_id="s",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="v1",
        trade_management_preset=TradeManagementPreset.BALANCED,
        direction=SignalDirection.BUY,
        signal_timestamp=signal_timestamp,
        fill_timestamp=signal_timestamp,
        fill_price=100.0,
        initial_stop_loss=95.0,
        risk=5.0,
        realized_r=0.0,
    )


def test_split_cutoff_at_ratio():
    candles = [_candle(i) for i in range(10)]
    cutoff = split_cutoff_timestamp(candles, split_ratio=0.7)
    assert cutoff == START + timedelta(hours=7)


def test_split_cutoff_rejects_bad_ratio():
    candles = [_candle(0)]
    with pytest.raises(ValueError):
        split_cutoff_timestamp(candles, split_ratio=0.0)
    with pytest.raises(ValueError):
        split_cutoff_timestamp(candles, split_ratio=1.0)


def test_split_trades_partitions_by_cutoff():
    cutoff = START + timedelta(hours=5)
    trades = [_trade(START + timedelta(hours=i)) for i in range(10)]
    development, out_of_sample = split_trades(trades, cutoff)
    assert all(t.signal_timestamp < cutoff for t in development)
    assert all(t.signal_timestamp >= cutoff for t in out_of_sample)
    assert len(development) + len(out_of_sample) == 10


def test_three_way_cutoffs_at_ratios():
    candles = [_candle(i) for i in range(100)]
    cutoff1, cutoff2 = split_cutoff_timestamps(candles, dev_ratio=0.7, validation_ratio=0.15)
    assert cutoff1 == START + timedelta(hours=70)
    assert cutoff2 == START + timedelta(hours=85)


def test_three_way_cutoffs_reject_non_positive_dev_ratio():
    candles = [_candle(i) for i in range(10)]
    with pytest.raises(ValueError):
        split_cutoff_timestamps(candles, dev_ratio=0.0, validation_ratio=0.15)


def test_three_way_cutoffs_reject_non_positive_validation_ratio():
    candles = [_candle(i) for i in range(10)]
    with pytest.raises(ValueError):
        split_cutoff_timestamps(candles, dev_ratio=0.7, validation_ratio=0.0)


def test_three_way_cutoffs_reject_ratios_summing_to_one_or_more():
    candles = [_candle(i) for i in range(10)]
    with pytest.raises(ValueError):
        split_cutoff_timestamps(candles, dev_ratio=0.85, validation_ratio=0.15)  # sums to exactly 1
    with pytest.raises(ValueError):
        split_cutoff_timestamps(candles, dev_ratio=0.9, validation_ratio=0.2)  # sums past 1


def test_split_trades_three_way_partitions_by_two_cutoffs():
    cutoff1 = START + timedelta(hours=7)
    cutoff2 = START + timedelta(hours=9)
    trades = [_trade(START + timedelta(hours=i)) for i in range(10)]
    development, validation, final_oos = split_trades_three_way(trades, cutoff1, cutoff2)
    assert all(t.signal_timestamp < cutoff1 for t in development)
    assert all(cutoff1 <= t.signal_timestamp < cutoff2 for t in validation)
    assert all(t.signal_timestamp >= cutoff2 for t in final_oos)
    assert len(development) + len(validation) + len(final_oos) == 10
    assert len(development) == 7
    assert len(validation) == 2
    assert len(final_oos) == 1
