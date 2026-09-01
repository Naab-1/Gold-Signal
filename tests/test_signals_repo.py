from datetime import UTC, datetime, timedelta

from goldsignal.models.candle import Timeframe
from goldsignal.models.signal import (
    EntryOrderType,
    ProfitTarget,
    SignalDirection,
    StrategyMode,
    StrategySignal,
)
from goldsignal.persistence.signals_repo import (
    LastSignalRecord,
    SignalFingerprint,
    fingerprint_of,
    is_duplicate,
)

TS = datetime(2026, 1, 15, 14, 0, tzinfo=UTC)


def _signal(*, stop_loss=2440.0, target_price=2470.6, direction=SignalDirection.BUY):
    if direction == SignalDirection.NO_TRADE:
        return StrategySignal(
            signal_id="s",
            instrument="XAUUSD",
            strategy_mode=StrategyMode.SCALP,
            strategy_version="v1",
            entry_timeframe=Timeframe.M5,
            confirmation_timeframe=Timeframe.M15,
            direction=direction,
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
    return StrategySignal(
        signal_id="s",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=direction,
        signal_timestamp=TS,
        entry_price=2450.2,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=stop_loss,
        targets=[ProfitTarget(label="TP1", price=target_price, r_multiple=2.0)],
        setup_expiration=TS + timedelta(minutes=15),
        invalidation_conditions=["x"],
        estimated_spread=0.3,
        estimated_slippage=0.2,
    )


def test_fingerprint_of_captures_direction_stop_and_targets():
    fp = fingerprint_of(_signal())
    assert fp == SignalFingerprint(direction="BUY", stop_loss=2440.0, target_prices=(2470.6,))


def test_no_last_signal_is_never_a_duplicate():
    assert is_duplicate(fingerprint_of(_signal()), None) is False


def test_identical_trade_idea_is_a_duplicate():
    last = LastSignalRecord(fingerprint=fingerprint_of(_signal()), signal_timestamp=TS)
    new_fp = fingerprint_of(_signal())  # same stop/target, later candle in reality
    assert is_duplicate(new_fp, last) is True


def test_different_stop_is_not_a_duplicate():
    last = LastSignalRecord(
        fingerprint=fingerprint_of(_signal(stop_loss=2440.0)), signal_timestamp=TS
    )
    new_fp = fingerprint_of(_signal(stop_loss=2441.0))
    assert is_duplicate(new_fp, last) is False


def test_different_target_is_not_a_duplicate():
    last = LastSignalRecord(
        fingerprint=fingerprint_of(_signal(target_price=2470.6)), signal_timestamp=TS
    )
    new_fp = fingerprint_of(_signal(target_price=2475.0))
    assert is_duplicate(new_fp, last) is False


def test_opposite_direction_is_not_a_duplicate():
    last = LastSignalRecord(
        fingerprint=fingerprint_of(_signal(direction=SignalDirection.BUY)), signal_timestamp=TS
    )
    new_fp = fingerprint_of(
        _signal(direction=SignalDirection.SELL, stop_loss=2460.0, target_price=2430.0)
    )
    assert is_duplicate(new_fp, last) is False


def test_no_trade_is_never_a_duplicate():
    last = LastSignalRecord(fingerprint=fingerprint_of(_signal()), signal_timestamp=TS)
    no_trade_fp = fingerprint_of(_signal(direction=SignalDirection.NO_TRADE))
    assert is_duplicate(no_trade_fp, last) is False
