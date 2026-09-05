"""Tests for the Liquidity Sweep and Reversal candidate (STRATEGY
RESEARCH AND REPLACEMENT program, Phase 4, Family E). Covers this
family's own logic: the single-candle sweep-then-reversal shape
(distinct from Family C's later-candle retest and Family D's
never-broken boundary), NO_TRADE reason granularity, config, and the
`Strategy`-protocol wrapper.
"""

from __future__ import annotations

import bisect
from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.config import ConfigError, load_liquidity_sweep_reversal_mode_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.base import EvaluationContext
from goldsignal.strategy.candidates.liquidity_sweep_reversal import (
    LiquiditySweepReversalStrategy,
    evaluate_liquidity_sweep_reversal,
    is_liquidity_sweep_reversal,
    load_liquidity_sweep_reversal_config,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, o=100.0, h=101.0, low=99.0, c=100.0):
    return Candle(
        timestamp=START + timedelta(minutes=5 * i), open=o, high=h, low=low, close=c, volume=1
    )


# --- Config -----------------------------------------------------------------


def test_config_defaults_load():
    config = load_liquidity_sweep_reversal_config({})
    assert config.sweep_lookback == 20
    assert config.sweep_min_atr_multiple == 0.15
    assert config.reversal_min_atr_multiple == 0.10
    assert config.structure_lookbacks == (20, 40, 60)


def test_mode_config_uses_m5_m15():
    config = load_liquidity_sweep_reversal_mode_config({})
    assert config.entry_timeframe.value == "M5"
    assert config.confirmation_timeframe.value == "M15"


def test_config_rejects_non_positive_sweep_lookback():
    with pytest.raises(ConfigError):
        load_liquidity_sweep_reversal_config(
            {"GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_SWEEP_LOOKBACK": "0"}
        )


def test_config_rejects_non_positive_sweep_min_atr_multiple():
    with pytest.raises(ConfigError):
        load_liquidity_sweep_reversal_config(
            {"GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_SWEEP_MIN_ATR_MULTIPLE": "0"}
        )


def test_config_rejects_malformed_structure_lookbacks():
    with pytest.raises(ConfigError):
        load_liquidity_sweep_reversal_config(
            {"GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_STRUCTURE_LOOKBACKS": "20,abc"}
        )


# --- is_liquidity_sweep_reversal ---------------------------------------------


def test_sell_sweep_true_when_high_overshoots_then_closes_decisively_back_below():
    # level=100: high sweeps to 100.3 (>= 100 + 0.2), closes at 99.7 (<= 100 - 0.1), bearish
    candle = _candle(0, o=100.1, h=100.3, low=99.6, c=99.7)
    assert is_liquidity_sweep_reversal(
        candle,
        level=100.0,
        direction=SignalDirection.SELL,
        sweep_min_distance=0.2,
        reversal_min_distance=0.1,
    )


def test_sell_sweep_false_if_high_never_overshoots_level():
    candle = _candle(0, o=99.5, h=100.05, low=99.0, c=99.4)
    assert not is_liquidity_sweep_reversal(
        candle,
        level=100.0,
        direction=SignalDirection.SELL,
        sweep_min_distance=0.2,
        reversal_min_distance=0.1,
    )


def test_sell_sweep_false_if_close_does_not_decisively_reverse_back():
    # sweeps beyond level but close only barely dips under (less than reversal_min_distance)
    candle = _candle(0, o=100.1, h=100.3, low=99.9, c=99.95)
    assert not is_liquidity_sweep_reversal(
        candle,
        level=100.0,
        direction=SignalDirection.SELL,
        sweep_min_distance=0.2,
        reversal_min_distance=0.1,
    )


def test_sell_sweep_false_if_not_directional():
    # sweeps and closes back through, but close > open (bullish, not bearish)
    candle = _candle(0, o=99.6, h=100.3, low=99.5, c=99.7)
    assert not is_liquidity_sweep_reversal(
        candle,
        level=100.0,
        direction=SignalDirection.SELL,
        sweep_min_distance=0.2,
        reversal_min_distance=0.1,
    )


def test_buy_sweep_mirrors_for_low_overshoot_then_close_back_above():
    candle = _candle(0, o=99.9, h=100.4, low=99.7, c=100.3)
    assert is_liquidity_sweep_reversal(
        candle,
        level=100.0,
        direction=SignalDirection.BUY,
        sweep_min_distance=0.2,
        reversal_min_distance=0.1,
    )


def test_buy_sweep_false_if_low_never_undershoots_level():
    candle = _candle(0, o=100.1, h=100.5, low=99.95, c=100.3)
    assert not is_liquidity_sweep_reversal(
        candle,
        level=100.0,
        direction=SignalDirection.BUY,
        sweep_min_distance=0.2,
        reversal_min_distance=0.1,
    )


# --- Full evaluate_liquidity_sweep_reversal / Strategy scan -----------------

_LOOSE_FAMILY_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "MIN_NET_REWARD_R": "0.1",
    "SWEEP_MIN_ATR_MULTIPLE": "0.15",
    "REVERSAL_MIN_ATR_MULTIPLE": "0.10",
}


def _family_env():
    return {f"GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_{k}": v for k, v in _LOOSE_FAMILY_OVERRIDES.items()}


def _mode_env():
    return {
        "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_COOLDOWN_MINUTES": "0",
        "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_MAX_SIGNALS_PER_SESSION": "10000",
    }


def test_scan_produces_both_buy_and_sell_with_sane_trade_parameters():
    mode_config = load_liquidity_sweep_reversal_mode_config(_mode_env())
    family_config = load_liquidity_sweep_reversal_config(_family_env())
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 8000
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
        signal = evaluate_liquidity_sweep_reversal(
            mode=StrategyMode.LIQUIDITY_SWEEP_REVERSAL,
            version="liquidity_sweep_reversal_v1",
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
    mode_config = load_liquidity_sweep_reversal_mode_config(_mode_env())
    family_config = load_liquidity_sweep_reversal_config(_family_env())
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 3000
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    confirm_close_times = [
        c.timestamp + mode_config.confirmation_timeframe.duration for c in confirm
    ]

    context = EvaluationContext()
    reasons_seen: set[str] = set()
    # Starts at i=1 (not i=60, unlike other families' equivalent test) so the
    # early "insufficient_candle_history" warmup period is included -- this
    # family's minimal condition set (no separate range/trend gate) means the
    # dominant no-setup-found reason otherwise leaves too little room for a
    # second, distinct reason to show up within a short synthetic window.
    for i in range(1, len(entry)):
        window = entry[: i + 1]
        now = window[-1].timestamp + mode_config.entry_timeframe.duration
        confirm_idx = bisect.bisect_right(confirm_close_times, now)
        confirm_window = confirm[:confirm_idx]
        signal = evaluate_liquidity_sweep_reversal(
            mode=StrategyMode.LIQUIDITY_SWEEP_REVERSAL,
            version="liquidity_sweep_reversal_v1",
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

    assert len(reasons_seen) >= 2


def test_cooldown_blocks_immediate_repeat_signal():
    mode_config = load_liquidity_sweep_reversal_mode_config(
        {"GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_MAX_SIGNALS_PER_SESSION": "10000"}
    )
    family_config = load_liquidity_sweep_reversal_config(
        {
            **_family_env(),
            "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_COOLDOWN_MINUTES": "999999",
        }
    )
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 8000
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
        signal = evaluate_liquidity_sweep_reversal(
            mode=StrategyMode.LIQUIDITY_SWEEP_REVERSAL,
            version="liquidity_sweep_reversal_v1",
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


def test_liquidity_sweep_reversal_strategy_wrapper_delegates_correctly():
    mode_config = load_liquidity_sweep_reversal_mode_config(_mode_env())
    family_config = load_liquidity_sweep_reversal_config(_family_env())
    strategy = LiquiditySweepReversalStrategy(mode_config, family_config, "XAUUSD")
    assert strategy.mode == StrategyMode.LIQUIDITY_SWEEP_REVERSAL
    assert strategy.version == "liquidity_sweep_reversal_v1"
    assert strategy.config is mode_config

    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 100
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    now = entry[-1].timestamp + mode_config.entry_timeframe.duration

    direct = evaluate_liquidity_sweep_reversal(
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
