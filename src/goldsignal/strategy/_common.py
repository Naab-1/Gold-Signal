"""Shared rule-evaluation arithmetic for the trend/EMA/RSI/ATR strategy
family.

This is a private implementation detail, not a public "one strategy with
interchangeable timeframes" base class: `ScalpStrategy` and
`DayTradeStrategy` (in scalp.py / day_trade.py) each call this with their
own `mode`, `version`, and independently-configured `ModeConfig`, and each
owns its own public class/version so the two remain independently
configurable and independently backtestable. Factoring the arithmetic here
only avoids duplicating ~150 delicate lines twice — the same reasoning that
already justifies sharing `indicators/*` between the two modes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from goldsignal.config import ModeConfig
from goldsignal.indicators.atr import atr as compute_atr
from goldsignal.indicators.ema import ema as compute_ema
from goldsignal.indicators.rsi import rsi as compute_rsi
from goldsignal.indicators.structure import breakout_and_retest, recent_swing_levels
from goldsignal.models.candle import Candle
from goldsignal.models.signal import (
    EntryOrderType,
    ProfitTarget,
    SignalDirection,
    StrategyMode,
    StrategySignal,
)
from goldsignal.strategy.base import EvaluationContext, make_signal_id
from goldsignal.strategy.cost_model import estimate_costs
from goldsignal.strategy.stop_loss import compute_stop_loss
from goldsignal.strategy.targets import build_targets, candidate_structure_levels
from goldsignal.strategy.trace import (
    COOLDOWN_BLOCKED,
    COST_REJECTED,
    ENTRY_NOT_CONFIRMED,
    INDICATORS_UNAVAILABLE,
    INSUFFICIENT_DATA,
    NO_TREND_ALIGNMENT,
    SESSION_LIMIT_BLOCKED,
    SETUP_FAILED,
    SIGNAL_EMITTED,
    EvaluationTrace,
)

logger = logging.getLogger(__name__)

_ALL_CONDITIONS = (
    "entry_confirmation_trend_alignment",
    "not_choppy",
    "rsi_confirmation",
    "breakout_retest_confirmed",
    "sufficient_reward_after_costs",
)


def _min_required_candles(config: ModeConfig) -> int:
    return (
        max(
            config.ema_slow_period,
            config.rsi_period + 1,
            config.atr_period,
            config.structure_lookback + config.retest_confirm_window + 1,
        )
        + 1
    )


def _no_trade(
    *,
    mode: StrategyMode,
    version: str,
    instrument: str,
    entry_timeframe,
    confirmation_timeframe,
    signal_timestamp: datetime,
    conditions_met: list[str],
    conditions_failed: list[str],
    confidence_score: float,
    reason: str,
) -> StrategySignal:
    signal_id = make_signal_id(
        instrument=instrument,
        strategy_mode=mode,
        entry_timeframe=entry_timeframe,
        signal_timestamp=signal_timestamp,
        direction=SignalDirection.NO_TRADE,
        strategy_version=version,
    )
    logger.info(
        "NO_TRADE mode=%s instrument=%s reason=%s conditions_failed=%s",
        mode.value,
        instrument,
        reason,
        conditions_failed,
    )
    return StrategySignal(
        signal_id=signal_id,
        instrument=instrument,
        strategy_mode=mode,
        strategy_version=version,
        entry_timeframe=entry_timeframe,
        confirmation_timeframe=confirmation_timeframe,
        direction=SignalDirection.NO_TRADE,
        signal_timestamp=signal_timestamp,
        entry_price=None,
        entry_order_type=None,
        stop_loss=None,
        targets=[],
        setup_expiration=None,
        invalidation_conditions=[],
        estimated_spread=None,
        estimated_slippage=None,
        conditions_met=conditions_met,
        conditions_failed=conditions_failed,
        confidence_score=confidence_score,
        reason=reason,
    )


def evaluate_trend_ema_rsi_atr(
    *,
    mode: StrategyMode,
    version: str,
    config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    now: datetime,
    context: EvaluationContext | None = None,
) -> StrategySignal:
    """Thin wrapper over `evaluate_with_trace` for live callers that only
    need the StrategySignal. See that function for the full rule pipeline.
    """
    signal, _trace = evaluate_with_trace(
        mode=mode,
        version=version,
        config=config,
        instrument=instrument,
        entry_candles=entry_candles,
        confirmation_candles=confirmation_candles,
        now=now,
        context=context,
    )
    return signal


def evaluate_with_trace(
    *,
    mode: StrategyMode,
    version: str,
    config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    now: datetime,
    context: EvaluationContext | None = None,
) -> tuple[StrategySignal, EvaluationTrace]:
    """Evaluate the strategy AND return a diagnostic trace of which rule
    stage a candle reached — used by the analysis/frequency tooling to
    build a funnel without a second, drift-prone implementation of the
    rules. The returned StrategySignal is byte-for-byte what
    `evaluate_trend_ema_rsi_atr` has always returned; the trace is
    additive and never affects it.

    Cooldown/session-limit are checked in their original position (before
    indicators are computed), so the trace can't report candidate
    direction/conditions for candles blocked by them — an accepted, minor
    gap given how few candles that affects in practice (see trace.py).
    """
    context = context or EvaluationContext()
    entry_timeframe = config.entry_timeframe
    confirmation_timeframe = config.confirmation_timeframe

    signal_timestamp = (
        entry_candles[-1].timestamp + entry_timeframe.duration if entry_candles else now
    )

    def no_trade(
        reason: str, met: list[str] | None = None, failed: list[str] | None = None
    ) -> StrategySignal:
        met = met or []
        failed = failed or []
        total = len(met) + len(failed)
        confidence = (len(met) / total * 100.0) if total else 0.0
        return _no_trade(
            mode=mode,
            version=version,
            instrument=instrument,
            entry_timeframe=entry_timeframe,
            confirmation_timeframe=confirmation_timeframe,
            signal_timestamp=signal_timestamp,
            conditions_met=met,
            conditions_failed=failed,
            confidence_score=confidence,
            reason=reason,
        )

    def trace(
        stage: str, signal: StrategySignal, *, direction=None, conditions=None
    ) -> EvaluationTrace:
        return EvaluationTrace(
            timestamp=signal_timestamp,
            stage=stage,
            candidate_direction=direction,
            conditions=conditions or {},
            signal=signal,
        )

    min_entry_candles = _min_required_candles(config)
    min_confirm_candles = config.ema_slow_period + 1
    if len(entry_candles) < min_entry_candles or len(confirmation_candles) < min_confirm_candles:
        signal = no_trade("insufficient_candle_history")
        return signal, trace(INSUFFICIENT_DATA, signal)

    if context.last_signal_time is not None:
        elapsed = now - context.last_signal_time
        if elapsed < timedelta(minutes=config.cooldown_minutes):
            signal = no_trade("cooldown_active")
            return signal, trace(COOLDOWN_BLOCKED, signal)

    if context.signals_emitted_this_session >= config.max_signals_per_session:
        signal = no_trade("max_signals_per_session_reached")
        return signal, trace(SESSION_LIMIT_BLOCKED, signal)

    entry_closes = [c.close for c in entry_candles]
    ema_fast = compute_ema(entry_closes, config.ema_fast_period)
    ema_slow = compute_ema(entry_closes, config.ema_slow_period)
    rsi_vals = compute_rsi(entry_closes, config.rsi_period)
    atr_vals = compute_atr(entry_candles, config.atr_period)

    confirm_closes = [c.close for c in confirmation_candles]
    confirm_ema_fast = compute_ema(confirm_closes, config.ema_fast_period)
    confirm_ema_slow = compute_ema(confirm_closes, config.ema_slow_period)

    if (
        ema_fast[-1] is None
        or ema_slow[-1] is None
        or rsi_vals[-1] is None
        or atr_vals[-1] is None
        or confirm_ema_fast[-1] is None
        or confirm_ema_slow[-1] is None
    ):
        signal = no_trade("indicators_unavailable")
        return signal, trace(INDICATORS_UNAVAILABLE, signal)

    current_ema_fast, current_ema_slow = ema_fast[-1], ema_slow[-1]
    current_rsi, current_atr = rsi_vals[-1], atr_vals[-1]
    confirm_trend_up = confirm_ema_fast[-1] > confirm_ema_slow[-1]
    confirm_trend_down = confirm_ema_fast[-1] < confirm_ema_slow[-1]
    entry_trend_up = current_ema_fast > current_ema_slow
    entry_trend_down = current_ema_fast < current_ema_slow

    if entry_trend_up and confirm_trend_up:
        direction = SignalDirection.BUY
    elif entry_trend_down and confirm_trend_down:
        direction = SignalDirection.SELL
    else:
        signal = no_trade(
            "entry_and_confirmation_timeframe_trends_not_aligned",
            failed=["entry_confirmation_trend_alignment"],
        )
        return signal, trace(NO_TREND_ALIGNMENT, signal)

    met = ["entry_confirmation_trend_alignment"]
    failed: list[str] = []

    not_choppy = (
        abs(current_ema_fast - current_ema_slow) >= config.chop_filter_atr_multiple * current_atr
    )
    (met if not_choppy else failed).append("not_choppy")

    if direction == SignalDirection.BUY:
        rsi_ok = config.rsi_buy_threshold <= current_rsi < config.rsi_overbought
    else:
        rsi_ok = config.rsi_oversold < current_rsi <= config.rsi_sell_threshold
    (met if rsi_ok else failed).append("rsi_confirmation")

    # Exclude the whole retest-confirmation window from the level calculation
    # itself, so the level is set BEFORE the candles being scanned for a
    # breakout+retest, rather than overlapping with (and being defined by)
    # them — otherwise a breakout could almost never close beyond a level
    # that its own candle helped set.
    resistance, support = recent_swing_levels(
        entry_candles, config.structure_lookback, exclude_last=config.retest_confirm_window
    )
    breakout_level = resistance if direction == SignalDirection.BUY else support
    tolerance = config.retest_tolerance_atr_fraction * current_atr
    retest_confirmed = breakout_level is not None and breakout_and_retest(
        entry_candles,
        breakout_level,
        bullish=(direction == SignalDirection.BUY),
        tolerance=tolerance,
        confirm_window=config.retest_confirm_window,
    )
    (met if retest_confirmed else failed).append("breakout_retest_confirmed")

    conditions = {
        "not_choppy": not_choppy,
        "rsi_confirmation": rsi_ok,
        "breakout_retest_confirmed": retest_confirmed,
    }
    if not not_choppy or not rsi_ok:
        signal = no_trade("one_or_more_confirmation_conditions_failed", met=met, failed=failed)
        return signal, trace(SETUP_FAILED, signal, direction=direction, conditions=conditions)
    if not retest_confirmed:
        signal = no_trade("one_or_more_confirmation_conditions_failed", met=met, failed=failed)
        return signal, trace(
            ENTRY_NOT_CONFIRMED, signal, direction=direction, conditions=conditions
        )

    entry_price = entry_candles[-1].close
    structural_ref = support if direction == SignalDirection.BUY else resistance
    stop_loss = compute_stop_loss(
        direction=direction,
        entry_price=entry_price,
        atr=current_atr,
        atr_stop_multiplier=config.atr_stop_multiplier,
        structural_ref=structural_ref,
        tolerance=tolerance,
    )

    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        signal = no_trade(
            "invalid_risk_distance", met=met, failed=[*failed, "sufficient_reward_after_costs"]
        )
        return signal, trace(COST_REJECTED, signal, direction=direction, conditions=conditions)

    costs = estimate_costs(
        config.estimated_spread, config.estimated_slippage, config.estimated_transaction_cost
    )
    lookbacks = [
        config.structure_lookback,
        config.structure_lookback * 2,
        config.structure_lookback * 3,
    ]
    candidate_levels = candidate_structure_levels(
        entry_candles, direction=direction, lookbacks=lookbacks
    )
    allow_tp3 = (
        abs(current_ema_fast - current_ema_slow) >= config.trend_strength_atr_multiple * current_atr
    )
    targets: list[ProfitTarget] = build_targets(
        direction=direction,
        entry=entry_price,
        stop_loss=stop_loss,
        candidate_levels=candidate_levels,
        costs=costs,
        min_net_reward_r=config.min_net_reward_r,
        allow_tp3=allow_tp3,
    )

    conditions["sufficient_reward_after_costs"] = bool(targets)
    if not targets:
        signal = no_trade(
            "no_target_clears_minimum_net_reward_after_costs",
            met=met,
            failed=[*failed, "sufficient_reward_after_costs"],
        )
        return signal, trace(COST_REJECTED, signal, direction=direction, conditions=conditions)
    met.append("sufficient_reward_after_costs")

    setup_expiration = signal_timestamp + config.setup_expiration_candles * entry_timeframe.duration
    breakout_word = "above" if direction == SignalDirection.BUY else "below"
    invalidation_conditions = [
        f"price closes back {'below' if direction == SignalDirection.BUY else 'above'} "
        f"the breakout level {breakout_level:.2f} before entry is filled",
        f"setup not filled by {setup_expiration.isoformat()}",
    ]

    signal_id = make_signal_id(
        instrument=instrument,
        strategy_mode=mode,
        entry_timeframe=entry_timeframe,
        signal_timestamp=signal_timestamp,
        direction=direction,
        strategy_version=version,
    )
    confidence = len(met) / len(_ALL_CONDITIONS) * 100.0
    reason = (
        f"{direction.value}: entry/confirmation trend aligned {breakout_word} "
        f"{breakout_level:.2f} with RSI and retest confirmation"
    )

    logger.info(
        "%s mode=%s instrument=%s entry=%.2f stop=%.2f targets=%s confidence=%.0f",
        direction.value,
        mode.value,
        instrument,
        entry_price,
        stop_loss,
        [(t.label, t.price, t.r_multiple) for t in targets],
        confidence,
    )

    signal = StrategySignal(
        signal_id=signal_id,
        instrument=instrument,
        strategy_mode=mode,
        strategy_version=version,
        entry_timeframe=entry_timeframe,
        confirmation_timeframe=confirmation_timeframe,
        direction=direction,
        signal_timestamp=signal_timestamp,
        entry_price=entry_price,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=stop_loss,
        targets=targets,
        setup_expiration=setup_expiration,
        invalidation_conditions=invalidation_conditions,
        estimated_spread=config.estimated_spread,
        estimated_slippage=config.estimated_slippage,
        conditions_met=met,
        conditions_failed=failed,
        confidence_score=confidence,
        reason=reason,
    )
    return signal, trace(SIGNAL_EMITTED, signal, direction=direction, conditions=conditions)
