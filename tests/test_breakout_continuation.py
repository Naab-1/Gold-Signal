"""Tests for the Breakout Continuation candidate (STRATEGY RESEARCH AND
REPLACEMENT program, Phase 4, Family B). The breakout/confirmation
candle-shape predicates themselves are already exhaustively tested in
`tests/test_continuation_rule.py` (reused here unchanged, not
re-derived) -- these tests cover this family's own orchestration: level
detection, direction selection, stop/target construction, NO_TRADE
reasons, config, and the `Strategy`-protocol wrapper.
"""

from __future__ import annotations

import bisect
from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.config import ConfigError, load_breakout_continuation_mode_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.base import EvaluationContext
from goldsignal.strategy.candidates.breakout_continuation import (
    BreakoutContinuationStrategy,
    evaluate_breakout_continuation,
    load_breakout_continuation_config,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, o=100.0, h=101.0, low=99.0, c=100.0):
    return Candle(
        timestamp=START + timedelta(minutes=5 * i), open=o, high=h, low=low, close=c, volume=1
    )


# --- Config -----------------------------------------------------------------


def test_config_defaults_load():
    config = load_breakout_continuation_config({})
    assert config.level_lookback == 20
    assert config.structure_lookbacks == (20, 40, 60)


def test_mode_config_uses_m5_m15():
    config = load_breakout_continuation_mode_config({})
    assert config.entry_timeframe.value == "M5"
    assert config.confirmation_timeframe.value == "M15"


def test_config_rejects_bad_body_ratio():
    with pytest.raises(ConfigError):
        load_breakout_continuation_config(
            {"GOLDSIGNAL_BREAKOUTCONTINUATION_CONTINUATION_MIN_BODY_RATIO": "1.5"}
        )


def test_config_rejects_bad_close_position_ratio():
    with pytest.raises(ConfigError):
        load_breakout_continuation_config(
            {"GOLDSIGNAL_BREAKOUTCONTINUATION_CONTINUATION_CLOSE_POSITION_RATIO": "0.6"}
        )


def test_config_rejects_malformed_structure_lookbacks():
    with pytest.raises(ConfigError):
        load_breakout_continuation_config(
            {"GOLDSIGNAL_BREAKOUTCONTINUATION_STRUCTURE_LOOKBACKS": "20,abc"}
        )


def test_config_rejects_non_positive_level_lookback():
    with pytest.raises(ConfigError):
        load_breakout_continuation_config({"GOLDSIGNAL_BREAKOUTCONTINUATION_LEVEL_LOOKBACK": "0"})


# --- Full evaluate_breakout_continuation / Strategy scan --------------------

_LOOSE_FAMILY_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "MIN_NET_REWARD_R": "0.1",
}


def _family_env():
    return {f"GOLDSIGNAL_BREAKOUTCONTINUATION_{k}": v for k, v in _LOOSE_FAMILY_OVERRIDES.items()}


def _mode_env():
    return {
        "GOLDSIGNAL_BREAKOUTCONTINUATION_COOLDOWN_MINUTES": "0",
        "GOLDSIGNAL_BREAKOUTCONTINUATION_MAX_SIGNALS_PER_SESSION": "10000",
    }


def test_scan_produces_both_buy_and_sell_with_sane_trade_parameters():
    mode_config = load_breakout_continuation_mode_config(_mode_env())
    family_config = load_breakout_continuation_config(_family_env())
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
        signal = evaluate_breakout_continuation(
            mode=StrategyMode.BREAKOUT_CONTINUATION,
            version="breakout_continuation_v1",
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
    mode_config = load_breakout_continuation_mode_config(_mode_env())
    family_config = load_breakout_continuation_config(_family_env())
    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 500
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
        signal = evaluate_breakout_continuation(
            mode=StrategyMode.BREAKOUT_CONTINUATION,
            version="breakout_continuation_v1",
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

    assert len(reasons_seen) > 1


def test_cooldown_blocks_immediate_repeat_signal():
    mode_config = load_breakout_continuation_mode_config(
        {"GOLDSIGNAL_BREAKOUTCONTINUATION_MAX_SIGNALS_PER_SESSION": "10000"}
    )
    family_config = load_breakout_continuation_config(
        {
            **_family_env(),
            "GOLDSIGNAL_BREAKOUTCONTINUATION_COOLDOWN_MINUTES": "999999",
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
        signal = evaluate_breakout_continuation(
            mode=StrategyMode.BREAKOUT_CONTINUATION,
            version="breakout_continuation_v1",
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


def test_breakout_continuation_strategy_wrapper_delegates_correctly():
    mode_config = load_breakout_continuation_mode_config(_mode_env())
    family_config = load_breakout_continuation_config(_family_env())
    strategy = BreakoutContinuationStrategy(mode_config, family_config, "XAUUSD")
    assert strategy.mode == StrategyMode.BREAKOUT_CONTINUATION
    assert strategy.version == "breakout_continuation_v1"
    assert strategy.config is mode_config

    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 100
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)
    now = entry[-1].timestamp + mode_config.entry_timeframe.duration

    direct = evaluate_breakout_continuation(
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
