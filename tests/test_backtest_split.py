from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.backtest.models import BacktestTrade
from goldsignal.backtest.split import split_cutoff_timestamp, split_trades
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
