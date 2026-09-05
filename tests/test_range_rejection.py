"""Tests for the Range Rejection candidate (STRATEGY RESEARCH AND
REPLACEMENT program, Phase 4, Family D). Covers this family's own
logic: the range-width-in-ATR-terms bound, the "not trending" ceiling
check (the mirror image of Family A's established-trend floor check),
the boundary-rejection shape, NO_TRADE reason granularity, config, and
the `Strategy`-protocol wrapper.
"""

from __future__ import annotations

import bisect
from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.config import ConfigError, load_range_rejection_mode_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.base import EvaluationContext
from goldsignal.strategy.candidates.range_rejection import (
    RangeRejectionStrategy,
    evaluate_range_rejection,
    is_range_boundary_rejection,
    is_ranging_market,
    is_valid_range_width,
    load_range_rejection_config,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, o=100.0, h=101.0, low=99.0, c=100.0):
    return Candle(
        timestamp=START + timedelta(minutes=15 * i), open=o, high=h, low=low, close=c, volume=1
    )


# --- Config -----------------------------------------------------------------


def test_config_defaults_load():
    config = load_range_rejection_config({})
    assert config.range_lookback == 20
    assert config.min_range_width_atr_multiple == 1.5
    assert config.max_range_width_atr_multiple == 6.0
    assert config.max_trend_strength_atr_multiple == 0.5
    assert config.structure_lookbacks == (20, 40, 60)


def test_mode_config_uses_m15_h1():
    config = load_range_rejection_mode_config({})
    assert config.entry_timeframe.value == "M15"
    assert config.confirmation_timeframe.value == "H1"


def test_config_rejects_non_positive_range_lookback():
    with pytest.raises(ConfigError):
        load_range_rejection_config({"GOLDSIGNAL_RANGEREJECTION_RANGE_LOOKBACK": "0"})


def test_config_rejects_max_width_not_greater_than_min_width():
    with pytest.raises(ConfigError):
        load_range_rejection_config(
            {
                "GOLDSIGNAL_RANGEREJECTION_MIN_RANGE_WIDTH_ATR_MULTIPLE": "3.0",
                "GOLDSIGNAL_RANGEREJECTION_MAX_RANGE_WIDTH_ATR_MULTIPLE": "3.0",
            }
        )


def test_config_rejects_malformed_structure_lookbacks():
    with pytest.raises(ConfigError):
        load_range_rejection_config({"GOLDSIGNAL_RANGEREJECTION_STRUCTURE_LOOKBACKS": "20,abc"})


# --- is_valid_range_width ----------------------------------------------------


def test_range_width_valid_within_bounds():
    assert is_valid_range_width(
        resistance=110, support=100, atr=5, min_multiple=1.0, max_multiple=4.0
    )


def test_range_width_invalid_too_narrow():
    assert not is_valid_range_width(
        resistance=102, support=100, atr=5, min_multiple=1.0, max_multiple=4.0
    )


def test_range_width_invalid_too_wide():
    assert not is_valid_range_width(
        resistance=130, support=100, atr=5, min_multiple=1.0, max_multiple=4.0
    )


def test_range_width_invalid_when_inverted():
    assert not is_valid_range_width(
        resistance=100, support=110, atr=5, min_multiple=1.0, max_multiple=4.0
    )


# --- is_ranging_market --------------------------------------------------------


def test_ranging_market_true_when_separation_below_ceiling():
    assert is_ranging_market(
        confirm_ema_fast=101.0,
        confirm_ema_slow=100.5,
        confirm_atr=5.0,
        max_trend_strength_atr_multiple=0.5,
    )


def test_ranging_market_false_when_strongly_trending_up():
    assert not is_ranging_market(
        confirm_ema_fast=105.0,
        confirm_ema_slow=100.0,
        confirm_atr=5.0,
        max_trend_strength_atr_multiple=0.5,
    )


def test_ranging_market_false_when_strongly_trending_down():
    assert not is_ranging_market(
        confirm_ema_fast=95.0,
        confirm_ema_slow=100.0,
        confirm_atr=5.0,
        max_trend_strength_atr_multiple=0.5,
    )


# --- is_range_boundary_rejection ----------------------------------------------


def test_boundary_rejection_true_for_buy_wick_into_support_then_close_up():
    candle = _candle(0, o=100.2, h=101, low=99.8, c=100.6)
    assert is_range_boundary_rejection(
        candle, level=100, direction=SignalDirection.BUY, tolerance=0.5
    )


def test_boundary_rejection_false_if_never_touches_level():
    candle = _candle(0, o=103, h=104, low=102, c=103.5)
    assert not is_range_boundary_rejection(
        candle, level=100, direction=SignalDirection.BUY, tolerance=0.5
    )


def test_boundary_rejection_false_if_closes_back_through_level():
    candle = _candle(0, o=100.5, h=101, low=99.5, c=99.6)
    assert not is_range_boundary_rejection(
        candle, level=100, direction=SignalDirection.BUY, tolerance=0.5
    )


def test_boundary_rejection_false_if_not_directional():
    candle = _candle(0, o=101, h=101.2, low=99.8, c=100.6)
    assert not is_range_boundary_rejection(
        candle, level=100, direction=SignalDirection.BUY, tolerance=0.5
    )


def test_boundary_rejection_mirrors_for_sell_at_resistance():
    candle = _candle(0, o=99.5, h=100.2, low=99, c=99.4)
    assert is_range_boundary_rejection(
        candle, level=100, direction=SignalDirection.SELL, tolerance=0.5
    )


# --- Full evaluate_range_rejection / Strategy scan --------------------------

_LOOSE_FAMILY_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "MIN_NET_REWARD_R": "0.1",
    "MIN_RANGE_WIDTH_ATR_MULTIPLE": "0.5",
    "MAX_RANGE_WIDTH_ATR_MULTIPLE": "10.0",
    "MAX_TREND_STRENGTH_ATR_MULTIPLE": "2.0",
    "REJECTION_TOLERANCE_ATR_FRACTION": "0.5",
}


def _family_env():
    return {f"GOLDSIGNAL_RANGEREJECTION_{k}": v for k, v in _LOOSE_FAMILY_OVERRIDES.items()}


def _mode_env():
    return {
        "GOLDSIGNAL_RANGEREJECTION_COOLDOWN_MINUTES": "0",
        "GOLDSIGNAL_RANGEREJECTION_MAX_SIGNALS_PER_SESSION": "10000",
    }


def test_scan_produces_both_buy_and_sell_with_sane_trade_parameters():
    mode_config = load_range_rejection_mode_config(_mode_env())
    family_config = load_range_rejection_config(_family_env())
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 6000
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    confirm_close_times = [
        c.timestamp + mode_config.confirmation_timeframe.duration for c in confirm
    ]

    context = EvaluationContext()
    seen_directions: set[SignalDirection] = set()

    for i in range(60, len(entry)):
        window = entry[: i + 1]
        now = window[-1].timestamp + mode_config.entry_timeframe.duration
        confirm_idx = bisect.bisect_right(confirm_close_times, now)
        confirm_window = confirm[:confirm_idx]
        signal = evaluate_range_rejection(
            mode=StrategyMode.RANGE_REJECTION,
            version="range_rejection_v1",
            mode_config=mode_config,
            family_config=family_config,
            instrument="XAUUSD",
            entry_candles=window,
            confirmation_candles=confirm_window,
            now=now,
            context=context,
        )
        if signal.direction != SignalDirection.NO_TRADE:
            seen_directions.add(signal.direction)
            assert signal.stop_loss is not None
            assert len(signal.targets) >= 1
            if signal.direction == SignalDirection.BUY:
                assert signal.stop_loss < signal.entry_price
                assert all(t.price > signal.entry_price for t in signal.targets)
            else:
                assert signal.stop_loss > signal.entry_price
                assert all(t.price < signal.entry_price for t in signal.targets)
            context = EvaluationContext(
                last_signal_time=signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )
        if seen_directions == {SignalDirection.BUY, SignalDirection.SELL}:
            break

    assert seen_directions == {SignalDirection.BUY, SignalDirection.SELL}


def test_no_trade_reasons_are_specific_not_blanket():
    mode_config = load_range_rejection_mode_config(_mode_env())
    family_config = load_range_rejection_config(_family_env())
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 1500
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    confirm_close_times = [
        c.timestamp + mode_config.confirmation_timeframe.duration for c in confirm
    ]

    context = EvaluationContext()
    reasons_seen: set[str] = set()
    for i in range(60, len(entry)):
        window = entry[: i + 1]
        now = window[-1].timestamp + mode_config.entry_timeframe.duration
        confirm_idx = bisect.bisect_right(confirm_close_times, now)
        confirm_window = confirm[:confirm_idx]
        signal = evaluate_range_rejection(
            mode=StrategyMode.RANGE_REJECTION,
            version="range_rejection_v1",
            mode_config=mode_config,
            family_config=family_config,
            instrument="XAUUSD",
            entry_candles=window,
            confirmation_candles=confirm_window,
            now=now,
            context=context,
        )
        if signal.direction == SignalDirection.NO_TRADE:
            reasons_seen.add(signal.reason)
        else:
            context = EvaluationContext(
                last_signal_time=signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )

    # Several distinct rejection stages, not one blanket "no setup" reason.
    assert len(reasons_seen) >= 3


def test_cooldown_blocks_immediate_repeat_signal():
    mode_config = load_range_rejection_mode_config(
        {"GOLDSIGNAL_RANGEREJECTION_MAX_SIGNALS_PER_SESSION": "10000"}
    )
    family_config = load_range_rejection_config(
        {
            **_family_env(),
            "GOLDSIGNAL_RANGEREJECTION_COOLDOWN_MINUTES": "999999",
        }
    )
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 6000
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    confirm_close_times = [
        c.timestamp + mode_config.confirmation_timeframe.duration for c in confirm
    ]

    context = EvaluationContext()
    got_first_signal = False
    for i in range(60, len(entry)):
        window = entry[: i + 1]
        now = window[-1].timestamp + mode_config.entry_timeframe.duration
        confirm_idx = bisect.bisect_right(confirm_close_times, now)
        confirm_window = confirm[:confirm_idx]
        signal = evaluate_range_rejection(
            mode=StrategyMode.RANGE_REJECTION,
            version="range_rejection_v1",
            mode_config=mode_config,
            family_config=family_config,
            instrument="XAUUSD",
            entry_candles=window,
            confirmation_candles=confirm_window,
            now=now,
            context=context,
        )
        if signal.direction != SignalDirection.NO_TRADE and not got_first_signal:
            got_first_signal = True
            context = EvaluationContext(
                last_signal_time=signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )
        elif got_first_signal:
            assert signal.direction == SignalDirection.NO_TRADE
            assert signal.reason == "cooldown_active"
            break

    assert got_first_signal


def test_range_rejection_strategy_wrapper_delegates_correctly():
    mode_config = load_range_rejection_mode_config(_mode_env())
    family_config = load_range_rejection_config(_family_env())
    strategy = RangeRejectionStrategy(mode_config, family_config, "XAUUSD")
    assert strategy.mode == StrategyMode.RANGE_REJECTION
    assert strategy.version == "range_rejection_v1"
    assert strategy.config is mode_config

    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 100
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    now = entry[-1].timestamp + mode_config.entry_timeframe.duration

    direct = evaluate_range_rejection(
        mode=strategy.mode,
        version=strategy.version,
        mode_config=mode_config,
        family_config=family_config,
        instrument="XAUUSD",
        entry_candles=entry,
        confirmation_candles=confirm,
        now=now,
    )
    via_wrapper = strategy.evaluate(entry, confirm, now=now)
    assert direct.direction == via_wrapper.direction
    assert direct.signal_id == via_wrapper.signal_id
