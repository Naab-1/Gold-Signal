"""Confirms a signal discovered late (during a catch-up sweep) is never
presented as a live, actionable entry once price has already run past its
stop or a target, or its setup window has expired.
"""

from __future__ import annotations

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
from goldsignal.strategy.actionability import is_still_actionable

TS = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _signal(
    *, direction=SignalDirection.BUY, entry=2450.0, stop=2445.0, targets=None, expiration=None
):
    return StrategySignal(
        signal_id="s",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=direction,
        signal_timestamp=TS,
        entry_price=entry,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=stop,
        targets=targets or [ProfitTarget(label="TP1", price=2460.0, r_multiple=2.0)],
        setup_expiration=expiration if expiration is not None else TS + timedelta(minutes=30),
        invalidation_conditions=[],
        estimated_spread=0.3,
        estimated_slippage=0.2,
    )


def test_fresh_buy_signal_still_actionable():
    signal = _signal(direction=SignalDirection.BUY, entry=2450.0, stop=2445.0)
    ok, reason = is_still_actionable(signal, now=TS, latest_price=2450.2)
    assert ok is True
    assert reason == ""


def test_expired_setup_is_not_actionable():
    signal = _signal(expiration=TS + timedelta(minutes=15))
    ok, reason = is_still_actionable(signal, now=TS + timedelta(minutes=16), latest_price=2450.0)
    assert ok is False
    assert "expired" in reason


def test_buy_already_stopped_out_is_not_actionable():
    signal = _signal(direction=SignalDirection.BUY, entry=2450.0, stop=2445.0)
    ok, reason = is_still_actionable(signal, now=TS + timedelta(minutes=5), latest_price=2444.0)
    assert ok is False
    assert "stop-loss" in reason


def test_sell_already_stopped_out_is_not_actionable():
    signal = _signal(
        direction=SignalDirection.SELL,
        entry=2450.0,
        stop=2455.0,
        targets=[ProfitTarget(label="TP1", price=2440.0, r_multiple=2.0)],
    )
    ok, reason = is_still_actionable(signal, now=TS + timedelta(minutes=5), latest_price=2456.0)
    assert ok is False
    assert "stop-loss" in reason


def test_buy_already_hit_target_is_not_actionable():
    signal = _signal(
        direction=SignalDirection.BUY,
        entry=2450.0,
        stop=2445.0,
        targets=[ProfitTarget(label="TP1", price=2460.0, r_multiple=2.0)],
    )
    ok, reason = is_still_actionable(signal, now=TS + timedelta(minutes=20), latest_price=2461.0)
    assert ok is False
    assert "TP1" in reason


def test_sell_already_hit_target_is_not_actionable():
    signal = _signal(
        direction=SignalDirection.SELL,
        entry=2450.0,
        stop=2455.0,
        targets=[ProfitTarget(label="TP1", price=2440.0, r_multiple=2.0)],
    )
    ok, reason = is_still_actionable(signal, now=TS + timedelta(minutes=20), latest_price=2439.0)
    assert ok is False
    assert "TP1" in reason


def test_price_still_between_entry_and_targets_is_actionable_even_when_late():
    signal = _signal(direction=SignalDirection.BUY, entry=2450.0, stop=2445.0)
    ok, reason = is_still_actionable(signal, now=TS + timedelta(minutes=10), latest_price=2452.0)
    assert ok is True
    assert reason == ""


def test_no_trade_signal_raises():
    no_trade = StrategySignal(
        signal_id="s",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="v1",
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
    with pytest.raises(ValueError):
        is_still_actionable(no_trade, now=TS, latest_price=2450.0)
