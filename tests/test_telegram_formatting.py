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
from goldsignal.notifications.formatting import (
    DISCLAIMER,
    format_no_trade_signal,
    format_trade_signal,
)

TS = datetime(2026, 1, 15, 14, 0, tzinfo=UTC)  # London-NY overlap window


def test_format_trade_signal_contains_required_fields():
    signal = StrategySignal(
        signal_id="abc",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="scalp_v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.BUY,
        signal_timestamp=TS,
        entry_price=2450.20,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=2440.00,
        targets=[ProfitTarget(label="TP1", price=2470.60, r_multiple=2.0)],
        setup_expiration=TS + timedelta(minutes=15),
        invalidation_conditions=["x", "y"],
        estimated_spread=0.3,
        estimated_slippage=0.2,
        reason="Uptrend + support retest + RSI confirmation",
    )

    text = format_trade_signal(signal)

    assert "SCALP" in text
    assert "BUY" in text
    assert "XAUUSD" in text
    assert "14:00 UTC" in text
    assert "Ghana" in text
    assert "2,450.20" in text
    assert "2,440.00" in text
    assert "TP1: 2,470.60 (2.0R)" in text
    assert "London" in text  # session label present
    assert "Uptrend + support retest + RSI confirmation" in text
    assert text.endswith("Paper-trading/research signal — not financial advice")


def test_format_trade_signal_rejects_no_trade():
    signal = StrategySignal(
        signal_id="abc",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="scalp_v1",
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
        format_trade_signal(signal)


def test_format_no_trade_signal():
    signal = StrategySignal(
        signal_id="abc",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.DAY_TRADE,
        strategy_version="daytrade_v1",
        entry_timeframe=Timeframe.M15,
        confirmation_timeframe=Timeframe.H1,
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
        reason="insufficient_candle_history",
        conditions_failed=["entry_confirmation_trend_alignment"],
    )
    text = format_no_trade_signal(signal)
    assert "DAY TRADE" in text
    assert "NO_TRADE" in text
    assert "insufficient_candle_history" in text
    assert "entry_confirmation_trend_alignment" in text
    assert text.endswith(DISCLAIMER)
