"""Verifies evaluate_with_trace's stages are consistent with the signal it
returns, and that evaluate_trend_ema_rsi_atr (the live wrapper) returns a
byte-identical StrategySignal to what evaluate_with_trace produces —
i.e. the refactor added visibility without changing live behavior.
"""

from datetime import UTC, datetime, timedelta

from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.signal import SignalDirection
from goldsignal.strategy._common import evaluate_trend_ema_rsi_atr, evaluate_with_trace
from goldsignal.strategy.base import EvaluationContext
from goldsignal.strategy.scalp import ScalpStrategy
from goldsignal.strategy.trace import (
    COOLDOWN_BLOCKED,
    COST_REJECTED,
    ENTRY_NOT_CONFIRMED,
    INSUFFICIENT_DATA,
    NO_TREND_ALIGNMENT,
    SESSION_LIMIT_BLOCKED,
    SETUP_FAILED,
    SIGNAL_EMITTED,
)

START = datetime(2026, 1, 1, tzinfo=UTC)

_LOOSE_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "ESTIMATED_SPREAD": "0.0",
    "ESTIMATED_SLIPPAGE": "0.0",
    "MIN_NET_REWARD_R": "0.1",
    "CHOP_FILTER_ATR_MULTIPLE": "0.05",
    "TREND_STRENGTH_ATR_MULTIPLE": "0.1",
    "RSI_BUY_THRESHOLD": "40",
    "RSI_SELL_THRESHOLD": "60",
    "RSI_OVERBOUGHT": "95",
    "RSI_OVERSOLD": "5",
    "RETEST_TOLERANCE_ATR_FRACTION": "1.0",
    "RETEST_CONFIRM_WINDOW": "10",
    "STRUCTURE_LOOKBACK": "8",
}


def _loose_env():
    return {f"GOLDSIGNAL_SCALP_{k}": v for k, v in _LOOSE_OVERRIDES.items()}


def test_insufficient_data_stage():
    config = load_scalp_config({})
    provider = MockDataProvider(seed=1)
    entry = provider.get_candles(
        "XAUUSD", config.entry_timeframe, START, START + config.entry_timeframe.duration * 3
    )
    confirm = provider.get_candles(
        "XAUUSD",
        config.confirmation_timeframe,
        START,
        START + config.confirmation_timeframe.duration * 3,
    )
    signal, tr = evaluate_with_trace(
        mode=ScalpStrategy(config, "XAUUSD").mode,
        version="v1",
        config=config,
        instrument="XAUUSD",
        entry_candles=entry,
        confirmation_candles=confirm,
        now=START + timedelta(days=1),
    )
    assert signal.direction == SignalDirection.NO_TRADE
    assert tr.stage == INSUFFICIENT_DATA
    assert tr.candidate_direction is None
    assert tr.conditions == {}


def test_cooldown_blocked_stage():
    config = load_scalp_config({"GOLDSIGNAL_SCALP_COOLDOWN_MINUTES": "30"})
    provider = MockDataProvider(seed=1)
    end = START + config.confirmation_timeframe.duration * 80
    entry = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)
    now = entry[-1].timestamp
    context = EvaluationContext(last_signal_time=now - timedelta(minutes=1))

    signal, tr = evaluate_with_trace(
        mode=ScalpStrategy(config, "XAUUSD").mode,
        version="v1",
        config=config,
        instrument="XAUUSD",
        entry_candles=entry,
        confirmation_candles=confirm,
        now=now,
        context=context,
    )
    assert signal.reason == "cooldown_active"
    assert tr.stage == COOLDOWN_BLOCKED


def test_session_limit_blocked_stage():
    config = load_scalp_config({"GOLDSIGNAL_SCALP_MAX_SIGNALS_PER_SESSION": "1"})
    provider = MockDataProvider(seed=1)
    end = START + config.confirmation_timeframe.duration * 80
    entry = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)
    now = entry[-1].timestamp
    context = EvaluationContext(signals_emitted_this_session=1)

    signal, tr = evaluate_with_trace(
        mode=ScalpStrategy(config, "XAUUSD").mode,
        version="v1",
        config=config,
        instrument="XAUUSD",
        entry_candles=entry,
        confirmation_candles=confirm,
        now=now,
        context=context,
    )
    assert signal.reason == "max_signals_per_session_reached"
    assert tr.stage == SESSION_LIMIT_BLOCKED


def test_wrapper_matches_trace_signal_exactly():
    """evaluate_trend_ema_rsi_atr (the live entry point) must return the
    exact same StrategySignal as the signal half of evaluate_with_trace,
    across many real scenarios — proving the refactor is behavior-preserving.
    """
    config = load_scalp_config(_loose_env())
    strategy = ScalpStrategy(config, "XAUUSD")
    provider = MockDataProvider(seed=3, base_price=2400.0, volatility=6.0)
    end = START + config.entry_timeframe.duration * 500
    entry_full = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm_full = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)

    stages_seen = set()
    for i in range(60, len(entry_full), 3):
        window = entry_full[:i]
        now = window[-1].timestamp + config.entry_timeframe.duration
        via_wrapper = evaluate_trend_ema_rsi_atr(
            mode=strategy.mode,
            version=strategy.version,
            config=config,
            instrument="XAUUSD",
            entry_candles=window,
            confirmation_candles=confirm_full,
            now=now,
        )
        via_trace, tr = evaluate_with_trace(
            mode=strategy.mode,
            version=strategy.version,
            config=config,
            instrument="XAUUSD",
            entry_candles=window,
            confirmation_candles=confirm_full,
            now=now,
        )
        assert via_wrapper == via_trace
        stages_seen.add(tr.stage)

        if tr.stage == SIGNAL_EMITTED:
            assert via_trace.direction != SignalDirection.NO_TRADE
            assert all(tr.conditions.values())
        elif tr.stage in (SETUP_FAILED, ENTRY_NOT_CONFIRMED, COST_REJECTED, NO_TREND_ALIGNMENT):
            assert via_trace.direction == SignalDirection.NO_TRADE

    assert SIGNAL_EMITTED in stages_seen, "expected at least one real signal across this scan"
