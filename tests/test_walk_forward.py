from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.backtest.models import BacktestTrade
from goldsignal.backtest.walk_forward import (
    aggregate_fold_trades,
    generate_walk_forward_folds,
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


def test_folds_have_expanding_train_windows():
    candles = [_candle(i) for i in range(30)]
    folds = generate_walk_forward_folds(candles, n_folds=3, min_train_candles=10)

    assert len(folds) == 3
    assert len(folds[0].train_candles) == 10
    assert len(folds[1].train_candles) > len(folds[0].train_candles)
    assert len(folds[2].train_candles) > len(folds[1].train_candles)
    # each train window is a strict prefix of candles, and grows monotonically
    for fold in folds:
        assert fold.train_candles == candles[: len(fold.train_candles)]


def test_validate_windows_are_disjoint_and_forward_only():
    candles = [_candle(i) for i in range(30)]
    folds = generate_walk_forward_folds(candles, n_folds=3, min_train_candles=10)

    seen_timestamps: set = set()
    last_end = None
    for fold in folds:
        ts = [c.timestamp for c in fold.validate_candles]
        assert not (seen_timestamps & set(ts)), "validate windows must not overlap"
        seen_timestamps.update(ts)
        if last_end is not None:
            assert min(ts) > last_end, "validate windows must move strictly forward"
        last_end = max(ts)


def test_last_fold_absorbs_remainder():
    # 30 candles, min_train=10 -> remaining=20, 3 folds -> validate_size=6 each,
    # but with a remainder that must land entirely in the last fold.
    candles = [_candle(i) for i in range(31)]
    folds = generate_walk_forward_folds(candles, n_folds=3, min_train_candles=10)

    total_validate = sum(len(f.validate_candles) for f in folds)
    assert total_validate == 21  # every candle after the first 10 is covered exactly once
    # last fold's validate window must extend to the very end of the series
    assert folds[-1].validate_candles[-1] == candles[-1]


def test_raises_when_not_enough_data_for_requested_folds():
    candles = [_candle(i) for i in range(10)]
    with pytest.raises(ValueError):
        generate_walk_forward_folds(candles, n_folds=5, min_train_candles=10)


def test_raises_on_non_positive_n_folds():
    candles = [_candle(i) for i in range(10)]
    with pytest.raises(ValueError):
        generate_walk_forward_folds(candles, n_folds=0, min_train_candles=5)


def test_raises_on_non_positive_min_train_candles():
    candles = [_candle(i) for i in range(10)]
    with pytest.raises(ValueError):
        generate_walk_forward_folds(candles, n_folds=2, min_train_candles=0)


def test_exact_boundary_count_succeeds():
    # exactly min_train_candles + n_folds candles: the minimum viable case,
    # each fold's validate window ends up with (close to) one candle.
    candles = [_candle(i) for i in range(12)]
    folds = generate_walk_forward_folds(candles, n_folds=2, min_train_candles=10)
    assert len(folds) == 2
    assert all(len(f.validate_candles) >= 1 for f in folds)


def test_aggregate_fold_trades_concatenates_in_order():
    fold_a = [_trade(START), _trade(START + timedelta(hours=1))]
    fold_b = [_trade(START + timedelta(hours=2))]
    result = aggregate_fold_trades([fold_a, fold_b])
    assert result == fold_a + fold_b


def test_aggregate_fold_trades_handles_empty_list():
    assert aggregate_fold_trades([]) == []
    assert aggregate_fold_trades([[], []]) == []
