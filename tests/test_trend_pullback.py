"""Tests for the Trend Pullback candidate (STRATEGY RESEARCH AND
REPLACEMENT program, Phase 4, Family A). Pure predicates get exact
hand-built fixtures; the full `evaluate_trend_pullback` pipeline uses a
long loosened-threshold scan over synthetic mock data, following the same
approach as `test_classification.py` -- hand-crafting exact candle
sequences that satisfy the full multi-indicator pipeline is fragile.
"""

from __future__ import annotations

import bisect
from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.config import ConfigError, load_trend_pullback_mode_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.base import EvaluationContext
from goldsignal.strategy.candidates.trend_pullback import (
    TrendPullbackStrategy,
    evaluate_trend_pullback,
    find_pullback_dip_index,
    is_established_trend,
    is_extended,
    is_first_rsi_crossing,
    load_trend_pullback_config,
    pullback_swing_extreme,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, o=100.0, h=101.0, low=99.0, c=100.0):
    return Candle(
        timestamp=START + timedelta(minutes=15 * i), open=o, high=h, low=low, close=c, volume=1
    )


# --- Config -----------------------------------------------------------------


def test_config_defaults_load():
    config = load_trend_pullback_config({})
    assert config.pullback_rsi_trigger == 40.0
    assert config.pullback_rsi_confirm == 50.0
    assert config.structure_lookbacks == (20, 40, 60)


def test_config_rejects_bad_rsi_trigger():
    with pytest.raises(ConfigError):
        load_trend_pullback_config({"GOLDSIGNAL_TRENDPULLBACK_PULLBACK_RSI_TRIGGER": "60"})


def test_config_rejects_bad_rsi_confirm():
    with pytest.raises(ConfigError):
        load_trend_pullback_config({"GOLDSIGNAL_TRENDPULLBACK_PULLBACK_RSI_CONFIRM": "40"})


def test_config_rejects_malformed_structure_lookbacks():
    with pytest.raises(ConfigError):
        load_trend_pullback_config({"GOLDSIGNAL_TRENDPULLBACK_STRUCTURE_LOOKBACKS": "20,abc"})


def test_mode_config_uses_m15_h1():
    config = load_trend_pullback_mode_config({})
    assert config.entry_timeframe.value == "M15"
    assert config.confirmation_timeframe.value == "H1"


# --- is_established_trend ----------------------------------------------------


def test_established_uptrend():
    direction = is_established_trend(
        confirm_ema_fast=105, confirm_ema_slow=100, confirm_atr=2, trend_strength_atr_multiple=1.0
    )
    assert direction == SignalDirection.BUY


def test_established_downtrend():
    direction = is_established_trend(
        confirm_ema_fast=100, confirm_ema_slow=105, confirm_atr=2, trend_strength_atr_multiple=1.0
    )
    assert direction == SignalDirection.SELL


def test_not_established_when_separation_too_small():
    direction = is_established_trend(
        confirm_ema_fast=100.5, confirm_ema_slow=100, confirm_atr=2, trend_strength_atr_multiple=1.0
    )
    assert direction is None


# --- find_pullback_dip_index --------------------------------------------------


def test_finds_most_recent_dip_for_uptrend():
    # RSI dips at index 5 and again more recently at index 8; must return 8.
    rsi = [60, 60, 60, 60, 60, 35, 60, 60, 30, 60, 60]
    dip = find_pullback_dip_index(
        rsi,
        direction=SignalDirection.BUY,
        current_idx=10,
        lookback_candles=20,
        pullback_rsi_trigger=40,
    )
    assert dip == 8


def test_no_dip_found_returns_none():
    rsi = [60] * 10
    dip = find_pullback_dip_index(
        rsi,
        direction=SignalDirection.BUY,
        current_idx=9,
        lookback_candles=20,
        pullback_rsi_trigger=40,
    )
    assert dip is None


def test_dip_outside_lookback_window_not_found():
    rsi = [35, 60, 60, 60, 60, 60, 60, 60, 60, 60]
    dip = find_pullback_dip_index(
        rsi,
        direction=SignalDirection.BUY,
        current_idx=9,
        lookback_candles=3,
        pullback_rsi_trigger=40,
    )
    assert dip is None


def test_downtrend_dip_uses_mirrored_threshold():
    rsi = [40, 40, 65, 40, 40]
    dip = find_pullback_dip_index(
        rsi,
        direction=SignalDirection.SELL,
        current_idx=4,
        lookback_candles=10,
        pullback_rsi_trigger=40,
    )
    assert dip == 2


# --- is_first_rsi_crossing (the ordered dip-then-first-crossing fix) --------


def test_first_crossing_after_dip_confirms():
    rsi = [60, 60, 35, 45, 55]  # dip at idx2, stays below 50 at idx3, crosses at idx4
    assert is_first_rsi_crossing(
        rsi, direction=SignalDirection.BUY, dip_idx=2, current_idx=4, pullback_rsi_confirm=50
    )


def test_not_yet_confirmed_current_still_below_threshold():
    rsi = [60, 60, 35, 45, 48]
    assert not is_first_rsi_crossing(
        rsi, direction=SignalDirection.BUY, dip_idx=2, current_idx=4, pullback_rsi_confirm=50
    )


def test_does_not_refire_on_a_later_uptick_after_the_first_crossing():
    """The exact bug the ordered-scan fix exists to prevent: RSI crosses
    back above 50 at idx3 (the real confirmation), dips slightly again
    without a fresh trigger-level dip, then ticks up again at idx5 -- idx5
    must NOT also count as a (second) confirmation of the same dip.
    """
    rsi = [60, 60, 35, 55, 48, 52]  # dip=2, confirmed at 3, idx5 must not re-confirm
    assert is_first_rsi_crossing(
        rsi, direction=SignalDirection.BUY, dip_idx=2, current_idx=3, pullback_rsi_confirm=50
    )
    assert not is_first_rsi_crossing(
        rsi, direction=SignalDirection.BUY, dip_idx=2, current_idx=5, pullback_rsi_confirm=50
    )


def test_downtrend_first_crossing_mirrors_threshold():
    rsi = [40, 40, 65, 55, 45]  # dip=2 (>=60), stays above 50 at idx3, crosses at idx4
    assert is_first_rsi_crossing(
        rsi, direction=SignalDirection.SELL, dip_idx=2, current_idx=4, pullback_rsi_confirm=50
    )


# --- pullback_swing_extreme / is_extended -----------------------------------


def test_pullback_swing_extreme_is_min_low_for_buy():
    candles = [_candle(0, low=95), _candle(1, low=90), _candle(2, low=93)]
    assert (
        pullback_swing_extreme(candles, direction=SignalDirection.BUY, dip_idx=0, current_idx=2)
        == 90
    )


def test_pullback_swing_extreme_is_max_high_for_sell():
    candles = [_candle(0, h=105), _candle(1, h=110), _candle(2, h=107)]
    assert (
        pullback_swing_extreme(candles, direction=SignalDirection.SELL, dip_idx=0, current_idx=2)
        == 110
    )


def test_is_extended_true_when_close_far_above_ema():
    assert is_extended(
        direction=SignalDirection.BUY,
        current_close=110,
        current_ema_fast=100,
        atr=2,
        max_extension_atr_multiple=1.5,
    )


def test_is_extended_false_when_close_near_ema():
    assert not is_extended(
        direction=SignalDirection.BUY,
        current_close=101,
        current_ema_fast=100,
        atr=2,
        max_extension_atr_multiple=1.5,
    )


def test_is_extended_mirrors_for_sell():
    assert is_extended(
        direction=SignalDirection.SELL,
        current_close=90,
        current_ema_fast=100,
        atr=2,
        max_extension_atr_multiple=1.5,
    )
    assert not is_extended(
        direction=SignalDirection.SELL,
        current_close=99,
        current_ema_fast=100,
        atr=2,
        max_extension_atr_multiple=1.5,
    )


# --- Full evaluate_trend_pullback / TrendPullbackStrategy scan --------------

_LOOSE_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "MIN_NET_REWARD_R": "0.1",
    "TREND_STRENGTH_ATR_MULTIPLE": "0.1",
}


def _family_env():
    return {f"GOLDSIGNAL_TRENDPULLBACK_{k}": v for k, v in _LOOSE_OVERRIDES.items()}


def _mode_env():
    return {
        "GOLDSIGNAL_TRENDPULLBACK_COOLDOWN_MINUTES": "0",
        "GOLDSIGNAL_TRENDPULLBACK_MAX_SIGNALS_PER_SESSION": "10000",
    }


def test_scan_produces_both_buy_and_sell_with_sane_trade_parameters():
    mode_config = load_trend_pullback_mode_config(_mode_env())
    family_config = load_trend_pullback_config(_family_env())
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 3000
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
        signal = evaluate_trend_pullback(
            mode=StrategyMode.TREND_PULLBACK,
            version="trend_pullback_v1",
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
    mode_config = load_trend_pullback_mode_config(_mode_env())
    family_config = load_trend_pullback_config(_family_env())
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 300
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
        signal = evaluate_trend_pullback(
            mode=StrategyMode.TREND_PULLBACK,
            version="trend_pullback_v1",
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

    # Not a blanket single reason for every rejection.
    assert len(reasons_seen) > 1


def test_cooldown_blocks_immediate_repeat_signal():
    mode_config = load_trend_pullback_mode_config(
        {"GOLDSIGNAL_TRENDPULLBACK_MAX_SIGNALS_PER_SESSION": "10000"}
    )
    family_config = load_trend_pullback_config(
        {
            **_family_env(),
            "GOLDSIGNAL_TRENDPULLBACK_COOLDOWN_MINUTES": "999999",
        }
    )
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 3000
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
        signal = evaluate_trend_pullback(
            mode=StrategyMode.TREND_PULLBACK,
            version="trend_pullback_v1",
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


def test_trend_pullback_strategy_wrapper_delegates_correctly():
    mode_config = load_trend_pullback_mode_config(_mode_env())
    family_config = load_trend_pullback_config(_family_env())
    strategy = TrendPullbackStrategy(mode_config, family_config, "XAUUSD")
    assert strategy.mode == StrategyMode.TREND_PULLBACK
    assert strategy.version == "trend_pullback_v1"
    assert strategy.config is mode_config

    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 100
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    now = entry[-1].timestamp + mode_config.entry_timeframe.duration

    direct = evaluate_trend_pullback(
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
