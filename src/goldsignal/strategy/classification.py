"""A+/A/WATCHLIST/NO_TRADE classification.

Layers the Two-Candle Continuation rule (the "A" tier, `continuation.py`)
on top of the existing, **unmodified** A+ rules (`_common.py`'s
`evaluate_with_trace`) — never a second implementation of the A+ decision
logic itself. Only pure math (indicators, stop placement, target
selection) is recomputed here, reusing the exact same shared functions
A+ already uses (`indicators/*`, `strategy/stop_loss.py`,
`strategy/targets.py`, `strategy/cost_model.py`).

WATCHLIST is a one-shot, two-step process exactly as specified: a
breakout candle creates a `PendingContinuation`; the very next candle
either confirms (-> A) or doesn't (-> resolved, not carried further).
Nothing here sends notifications or persists state — that's the next
plan, once A tier's real performance is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from goldsignal.config import ModeConfig
from goldsignal.indicators.atr import atr as compute_atr
from goldsignal.indicators.ema import ema as compute_ema
from goldsignal.indicators.structure import recent_swing_levels
from goldsignal.models.candle import Candle
from goldsignal.models.signal import (
    EntryOrderType,
    ProfitTarget,
    SignalDirection,
    StrategyMode,
    StrategySignal,
)
from goldsignal.strategy._common import evaluate_with_trace
from goldsignal.strategy.base import EvaluationContext, make_signal_id
from goldsignal.strategy.continuation import classify_breakout_candle, classify_confirmation_candle
from goldsignal.strategy.cost_model import estimate_costs
from goldsignal.strategy.stop_loss import compute_stop_loss
from goldsignal.strategy.targets import build_targets, candidate_structure_levels
from goldsignal.strategy.trace import SIGNAL_EMITTED


class SignalGrade(str, Enum):
    A_PLUS = "A_PLUS"
    A = "A"
    WATCHLIST = "WATCHLIST"
    NO_TRADE = "NO_TRADE"


@dataclass(frozen=True)
class PendingContinuation:
    direction: SignalDirection
    level: float
    breakout_close: float
    breakout_timestamp: datetime


@dataclass(frozen=True)
class ClassificationResult:
    grade: SignalGrade
    signal: StrategySignal | None  # populated for A_PLUS and A only
    pending: PendingContinuation | None  # carried to the next step for WATCHLIST


def _build_a_signal(
    *,
    mode: StrategyMode,
    version: str,
    config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    direction: SignalDirection,
    entry_timeframe,
    confirmation_timeframe,
    signal_timestamp: datetime,
    variant_tag: str,
    confirmed_condition: str,
    reason: str,
) -> StrategySignal | None:
    """Build an A-tier-style signal, reusing the exact stop/target/cost
    math A+ already uses, at the A-tier's own (1.5R default) minimum
    reward threshold. Returns None if the reward gate isn't cleared — per
    spec, the setup is not promoted.

    `variant_tag` distinguishes which alternative rule produced this
    signal (e.g. "two_candle_continuation" vs. "one_candle_breakout") so
    comparison statistics can never be blended across variants.
    """
    current_atr_vals = compute_atr(entry_candles, config.atr_period)
    current_atr = current_atr_vals[-1]
    if current_atr is None:
        return None

    ema_fast_vals = compute_ema([c.close for c in entry_candles], config.ema_fast_period)
    ema_slow_vals = compute_ema([c.close for c in entry_candles], config.ema_slow_period)
    if ema_fast_vals[-1] is None or ema_slow_vals[-1] is None:
        return None

    entry_price = entry_candles[-1].close
    resistance, support = recent_swing_levels(
        entry_candles, config.structure_lookback, exclude_last=config.retest_confirm_window
    )
    structural_ref = support if direction == SignalDirection.BUY else resistance
    tolerance = config.continuation_confirmation_tolerance_atr_fraction * current_atr

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
        return None

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
        abs(ema_fast_vals[-1] - ema_slow_vals[-1])
        >= config.trend_strength_atr_multiple * current_atr
    )
    targets: list[ProfitTarget] = build_targets(
        direction=direction,
        entry=entry_price,
        stop_loss=stop_loss,
        candidate_levels=candidate_levels,
        costs=costs,
        min_net_reward_r=config.a_tier_min_net_reward_r,
        allow_tp3=allow_tp3,
    )
    if not targets:
        return None

    setup_expiration = signal_timestamp + config.setup_expiration_candles * entry_timeframe.duration
    invalidation_conditions = [
        f"price closes back {'below' if direction == SignalDirection.BUY else 'above'} "
        f"the continuation level before entry is filled",
        f"setup not filled by {setup_expiration.isoformat()}",
    ]
    strategy_version = f"{version}+{variant_tag}"
    signal_id = make_signal_id(
        instrument=instrument,
        strategy_mode=mode,
        entry_timeframe=entry_timeframe,
        signal_timestamp=signal_timestamp,
        direction=direction,
        strategy_version=strategy_version,
    )
    met = [
        "entry_confirmation_trend_alignment",
        "not_choppy",
        "rsi_confirmation",
        confirmed_condition,
        "sufficient_reward_after_costs",
    ]
    confidence = 100.0

    return StrategySignal(
        signal_id=signal_id,
        instrument=instrument,
        strategy_mode=mode,
        strategy_version=strategy_version,
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
        conditions_failed=[],
        confidence_score=confidence,
        reason=reason,
    )


def evaluate_a_tier_continuation(
    *,
    mode: StrategyMode,
    version: str,
    config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    now: datetime,
    context: EvaluationContext | None = None,
    pending: PendingContinuation | None = None,
) -> ClassificationResult:
    """Standalone Two-Candle Breakout Continuation evaluator (WATCHLIST ->
    A), independent of whether the A+ rule fired. Reuses
    `evaluate_with_trace` only as a shared-math source for the
    trend/chop/RSI gate and candidate direction, not for its A+ verdict —
    so this can be walked in isolation for comparison purposes without
    ever touching A+ statistics.
    """
    context = context or EvaluationContext()
    _, trace = evaluate_with_trace(
        mode=mode,
        version=version,
        config=config,
        instrument=instrument,
        entry_candles=entry_candles,
        confirmation_candles=confirmation_candles,
        now=now,
        context=context,
    )

    current_candle = entry_candles[-1] if entry_candles else None
    atr_vals = compute_atr(entry_candles, config.atr_period) if entry_candles else []
    current_atr = atr_vals[-1] if atr_vals else None

    # Resolve any pending continuation FIRST, using only the two-candle
    # rule's own confirmation criteria (spec section 5) — this must NOT be
    # gated behind the broader trend/chop/RSI gates re-passing on this
    # same candle, since the spec never requires that; a breakout candle's
    # momentum push can easily make RSI/chop look different one candle
    # later without invalidating a textbook confirmation candle.
    if pending is not None and current_candle is not None and current_atr is not None:
        tolerance = config.continuation_confirmation_tolerance_atr_fraction * current_atr
        confirmed = classify_confirmation_candle(
            current_candle,
            level=pending.level,
            breakout_close=pending.breakout_close,
            direction=pending.direction,
            tolerance=tolerance,
        )
        if confirmed:
            signal_timestamp = current_candle.timestamp + config.entry_timeframe.duration
            a_signal = _build_a_signal(
                mode=mode,
                version=version,
                config=config,
                instrument=instrument,
                entry_candles=entry_candles,
                direction=pending.direction,
                entry_timeframe=config.entry_timeframe,
                confirmation_timeframe=config.confirmation_timeframe,
                signal_timestamp=signal_timestamp,
                variant_tag="two_candle_continuation",
                confirmed_condition="two_candle_continuation_confirmed",
                reason=(
                    f"{pending.direction.value}: two-candle continuation confirmed "
                    "(A tier, experimental)"
                ),
            )
            if a_signal is not None:
                return ClassificationResult(grade=SignalGrade.A, signal=a_signal, pending=None)
        # Either didn't confirm, or the reward gate failed after confirming:
        # this pending setup is resolved (cancelled/expired) either way — it
        # never carries forward beyond the one confirmation attempt.

    if not trace.conditions or not (
        trace.conditions.get("not_choppy") and trace.conditions.get("rsi_confirmation")
    ):
        return ClassificationResult(grade=SignalGrade.NO_TRADE, signal=None, pending=None)

    direction = trace.candidate_direction
    if direction is None or current_candle is None or current_atr is None:
        return ClassificationResult(grade=SignalGrade.NO_TRADE, signal=None, pending=None)

    resistance, support = recent_swing_levels(
        entry_candles, config.structure_lookback, exclude_last=config.retest_confirm_window
    )
    level = resistance if direction == SignalDirection.BUY else support

    if level is not None and classify_breakout_candle(
        current_candle, level=level, direction=direction, atr=current_atr, config=config
    ):
        new_pending = PendingContinuation(
            direction=direction,
            level=level,
            breakout_close=current_candle.close,
            breakout_timestamp=current_candle.timestamp,
        )
        return ClassificationResult(grade=SignalGrade.WATCHLIST, signal=None, pending=new_pending)

    return ClassificationResult(grade=SignalGrade.NO_TRADE, signal=None, pending=None)


def evaluate_one_candle_breakout(
    *,
    mode: StrategyMode,
    version: str,
    config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    now: datetime,
    context: EvaluationContext | None = None,
) -> ClassificationResult:
    """Comparison-only variant: the breakout candle's own qualifying
    filters (`continuation.classify_breakout_candle`) are treated as
    sufficient on their own, with no confirmation-candle wait. Never used
    by `classify()` / production — exists purely so its historical
    frequency and performance can be measured against the two-candle rule
    without blending the two into one statistic.
    """
    context = context or EvaluationContext()
    _, trace = evaluate_with_trace(
        mode=mode,
        version=version,
        config=config,
        instrument=instrument,
        entry_candles=entry_candles,
        confirmation_candles=confirmation_candles,
        now=now,
        context=context,
    )

    if not trace.conditions or not (
        trace.conditions.get("not_choppy") and trace.conditions.get("rsi_confirmation")
    ):
        return ClassificationResult(grade=SignalGrade.NO_TRADE, signal=None, pending=None)

    direction = trace.candidate_direction
    current_candle = entry_candles[-1] if entry_candles else None
    atr_vals = compute_atr(entry_candles, config.atr_period) if entry_candles else []
    current_atr = atr_vals[-1] if atr_vals else None
    if direction is None or current_candle is None or current_atr is None:
        return ClassificationResult(grade=SignalGrade.NO_TRADE, signal=None, pending=None)

    resistance, support = recent_swing_levels(
        entry_candles, config.structure_lookback, exclude_last=config.retest_confirm_window
    )
    level = resistance if direction == SignalDirection.BUY else support
    if level is None or not classify_breakout_candle(
        current_candle, level=level, direction=direction, atr=current_atr, config=config
    ):
        return ClassificationResult(grade=SignalGrade.NO_TRADE, signal=None, pending=None)

    signal_timestamp = current_candle.timestamp + config.entry_timeframe.duration
    signal = _build_a_signal(
        mode=mode,
        version=version,
        config=config,
        instrument=instrument,
        entry_candles=entry_candles,
        direction=direction,
        entry_timeframe=config.entry_timeframe,
        confirmation_timeframe=config.confirmation_timeframe,
        signal_timestamp=signal_timestamp,
        variant_tag="one_candle_breakout",
        confirmed_condition="one_candle_breakout_confirmed",
        reason=(
            f"{direction.value}: one-candle breakout confirmed "
            "(comparison variant only, not for production)"
        ),
    )
    if signal is None:
        return ClassificationResult(grade=SignalGrade.NO_TRADE, signal=None, pending=None)
    return ClassificationResult(grade=SignalGrade.A, signal=signal, pending=None)


def classify(
    *,
    mode: StrategyMode,
    version: str,
    config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    now: datetime,
    context: EvaluationContext | None = None,
    pending: PendingContinuation | None = None,
) -> ClassificationResult:
    context = context or EvaluationContext()

    signal, trace = evaluate_with_trace(
        mode=mode,
        version=version,
        config=config,
        instrument=instrument,
        entry_candles=entry_candles,
        confirmation_candles=confirmation_candles,
        now=now,
        context=context,
    )
    if trace.stage == SIGNAL_EMITTED:
        return ClassificationResult(grade=SignalGrade.A_PLUS, signal=signal, pending=None)

    return evaluate_a_tier_continuation(
        mode=mode,
        version=version,
        config=config,
        instrument=instrument,
        entry_candles=entry_candles,
        confirmation_candles=confirmation_candles,
        now=now,
        context=context,
        pending=pending,
    )
