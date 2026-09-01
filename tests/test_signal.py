from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.models.candle import Timeframe
from goldsignal.models.signal import (
    EntryOrderType,
    ProfitTarget,
    SignalDirection,
    StrategyMode,
    StrategySignal,
)

TS = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
EXPIRY = TS + timedelta(minutes=15)


def _base_kwargs(**overrides):
    kwargs = dict(
        signal_id="abc123",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="scalp_ema_rsi_atr_v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.BUY,
        signal_timestamp=TS,
        entry_price=2400.0,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=2395.0,
        targets=[ProfitTarget(label="TP1", price=2405.0, r_multiple=1.0)],
        setup_expiration=EXPIRY,
        invalidation_conditions=["close back below breakout level"],
        estimated_spread=0.3,
        estimated_slippage=0.2,
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_buy_signal_constructs():
    sig = StrategySignal(**_base_kwargs())
    assert sig.direction == SignalDirection.BUY
    assert sig.targets[0].label == "TP1"


def test_no_trade_signal_must_have_no_trade_params():
    with pytest.raises(ValueError):
        StrategySignal(**_base_kwargs(direction=SignalDirection.NO_TRADE))


def test_valid_no_trade_signal():
    sig = StrategySignal(
        signal_id="x",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="scalp_ema_rsi_atr_v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.NO_TRADE,
        signal_timestamp=TS,
        entry_price=None,
        entry_order_type=None,
        stop_loss=None,
        targets=[],
        setup_expiration=None,
        invalidation_conditions=[],
        estimated_spread=None,
        estimated_slippage=None,
    )
    assert sig.direction == SignalDirection.NO_TRADE


def test_buy_requires_at_least_one_target():
    with pytest.raises(ValueError):
        StrategySignal(**_base_kwargs(targets=[]))


def test_buy_targets_must_be_above_entry():
    bad = [ProfitTarget(label="TP1", price=2390.0, r_multiple=1.0)]
    with pytest.raises(ValueError):
        StrategySignal(**_base_kwargs(targets=bad))


def test_sell_targets_must_be_below_entry():
    bad = [ProfitTarget(label="TP1", price=2410.0, r_multiple=1.0)]
    with pytest.raises(ValueError):
        StrategySignal(
            **_base_kwargs(direction=SignalDirection.SELL, stop_loss=2405.0, targets=bad)
        )


def test_targets_must_be_ordered_and_increasing_r_multiple():
    # TP2 closer than TP1 for a BUY — wrong order
    bad = [
        ProfitTarget(label="TP1", price=2410.0, r_multiple=2.0),
        ProfitTarget(label="TP2", price=2405.0, r_multiple=1.0),
    ]
    with pytest.raises(ValueError):
        StrategySignal(**_base_kwargs(targets=bad))


def test_duplicate_target_prices_rejected():
    bad = [
        ProfitTarget(label="TP1", price=2405.0, r_multiple=1.0),
        ProfitTarget(label="TP2", price=2405.0, r_multiple=2.0),
    ]
    with pytest.raises(ValueError):
        StrategySignal(**_base_kwargs(targets=bad))


def test_more_than_three_targets_rejected():
    bad = [
        ProfitTarget(label="TP1", price=2401.0, r_multiple=0.2),
        ProfitTarget(label="TP2", price=2402.0, r_multiple=0.4),
        ProfitTarget(label="TP3", price=2403.0, r_multiple=0.6),
        ProfitTarget(label="TP1", price=2404.0, r_multiple=0.8),
    ]
    with pytest.raises(ValueError):
        StrategySignal(**_base_kwargs(targets=bad))


def test_buy_stop_loss_must_be_below_entry():
    with pytest.raises(ValueError):
        StrategySignal(**_base_kwargs(stop_loss=2405.0))


def test_setup_expiration_must_be_after_signal_timestamp():
    with pytest.raises(ValueError):
        StrategySignal(**_base_kwargs(setup_expiration=TS - timedelta(minutes=5)))
