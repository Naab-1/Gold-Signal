"""Breakout Continuation (STRATEGY RESEARCH AND REPLACEMENT program,
Phase 4, candidate Family B) -- see docs/phase4_breakout_continuation.md
for the full spec and reasoning.

Independent of, and never combined with, the frozen A+/A tiers -- but
reuses the frozen `strategy/continuation.py`'s pure, already-validated
`classify_breakout_candle`/`classify_confirmation_candle` predicates
UNCHANGED (imported, not modified or copied) rather than re-deriving the
same breakout/confirmation shape math a second time. Those two functions
are stateless and take their thresholds via explicit parameters/a
config-shaped object, so reusing them here doesn't touch, reinterpret, or
depend on anything about the rejected baseline's own orchestration
(classification.py) -- only the pure arithmetic is shared.

Unlike the frozen A-tier's stateful WATCHLIST-then-confirm design (a
`pending` object threaded between calls), this evaluator is fully
stateless per call, matching the `Strategy` Protocol's exact shape (no
`pending` parameter exists there) and `analysis/candidate_walk.py`'s
generic harness, which doesn't carry any such state between steps either:
each evaluation independently checks whether entry_candles[-2] was a
qualifying breakout candle (relative to a level computed from candles
strictly before both it and the current candle) and whether
entry_candles[-1] is its confirmation.

Rule, in one sentence: find a pre-existing swing level, require the
second-to-last candle to have broken it strongly (large enough beyond it,
strong body, closing near its extreme, without an oversized range that
would make the entry late) and the most recent candle to confirm that
break with a further, directional close that doesn't wick back through
the level.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from goldsignal.config import ConfigError, ModeConfig, _get, _parse_float, _parse_int
from goldsignal.indicators.atr import atr as compute_atr
from goldsignal.indicators.structure import recent_swing_levels
from goldsignal.models.candle import Candle
from goldsignal.models.signal import (
    EntryOrderType,
    ProfitTarget,
    SignalDirection,
    StrategyMode,
    StrategySignal,
)
from goldsignal.strategy.base import EvaluationContext, make_signal_id
from goldsignal.strategy.continuation import classify_breakout_candle, classify_confirmation_candle
from goldsignal.strategy.cost_model import estimate_costs
from goldsignal.strategy.stop_loss import compute_stop_loss
from goldsignal.strategy.targets import build_targets, candidate_structure_levels

STRATEGY_VERSION = "breakout_continuation_v1"

_ALL_CONDITIONS = (
    "level_found",
    "breakout_candle_qualified",
    "confirmation_candle_qualified",
    "sufficient_reward_after_costs",
)


# --- Family-specific config ---------------------------------------------


@dataclass(frozen=True)
class BreakoutContinuationConfig:
    level_lookback: int
    # Field names below deliberately match strategy/continuation.py's own
    # `classify_breakout_candle`'s expected config attribute names, so this
    # object can be passed directly to that frozen, unmodified function --
    # no adapter/shim needed for a handful of plain attribute reads.
    continuation_breakout_min_atr_multiple: float
    continuation_min_body_ratio: float
    continuation_close_position_ratio: float
    continuation_max_range_atr_multiple: float
    confirmation_tolerance_atr_fraction: float
    structure_lookbacks: tuple[int, ...]
    min_net_reward_r: float
    cooldown_minutes: int
    max_signals_per_session: int
    setup_expiration_candles: int


_BREAKOUTCONTINUATION_DEFAULTS: dict[str, str] = {
    "LEVEL_LOOKBACK": "20",
    "CONTINUATION_BREAKOUT_MIN_ATR_MULTIPLE": "0.10",
    "CONTINUATION_MIN_BODY_RATIO": "0.60",
    "CONTINUATION_CLOSE_POSITION_RATIO": "0.25",
    "CONTINUATION_MAX_RANGE_ATR_MULTIPLE": "2.0",
    "CONFIRMATION_TOLERANCE_ATR_FRACTION": "0.10",
    "STRUCTURE_LOOKBACKS": "20,40,60",
    "MIN_NET_REWARD_R": "1.5",
    "COOLDOWN_MINUTES": "30",
    "MAX_SIGNALS_PER_SESSION": "4",
    "SETUP_EXPIRATION_CANDLES": "3",
}


def load_breakout_continuation_config(
    env: Mapping[str, str] | None = None,
) -> BreakoutContinuationConfig:
    env = os.environ if env is None else env
    prefix = "BREAKOUTCONTINUATION_"
    defaults = _BREAKOUTCONTINUATION_DEFAULTS

    def var(name: str) -> str:
        return f"GOLDSIGNAL_{prefix}{name}"

    lookbacks_raw = _get(env, prefix, "STRUCTURE_LOOKBACKS", defaults)
    try:
        structure_lookbacks = tuple(int(x.strip()) for x in lookbacks_raw.split(","))
    except ValueError as exc:
        raise ConfigError(
            f"{var('STRUCTURE_LOOKBACKS')} must be a comma-separated int list"
        ) from exc

    config = BreakoutContinuationConfig(
        level_lookback=_parse_int(
            _get(env, prefix, "LEVEL_LOOKBACK", defaults), var("LEVEL_LOOKBACK")
        ),
        continuation_breakout_min_atr_multiple=_parse_float(
            _get(env, prefix, "CONTINUATION_BREAKOUT_MIN_ATR_MULTIPLE", defaults),
            var("CONTINUATION_BREAKOUT_MIN_ATR_MULTIPLE"),
        ),
        continuation_min_body_ratio=_parse_float(
            _get(env, prefix, "CONTINUATION_MIN_BODY_RATIO", defaults),
            var("CONTINUATION_MIN_BODY_RATIO"),
        ),
        continuation_close_position_ratio=_parse_float(
            _get(env, prefix, "CONTINUATION_CLOSE_POSITION_RATIO", defaults),
            var("CONTINUATION_CLOSE_POSITION_RATIO"),
        ),
        continuation_max_range_atr_multiple=_parse_float(
            _get(env, prefix, "CONTINUATION_MAX_RANGE_ATR_MULTIPLE", defaults),
            var("CONTINUATION_MAX_RANGE_ATR_MULTIPLE"),
        ),
        confirmation_tolerance_atr_fraction=_parse_float(
            _get(env, prefix, "CONFIRMATION_TOLERANCE_ATR_FRACTION", defaults),
            var("CONFIRMATION_TOLERANCE_ATR_FRACTION"),
        ),
        structure_lookbacks=structure_lookbacks,
        min_net_reward_r=_parse_float(
            _get(env, prefix, "MIN_NET_REWARD_R", defaults), var("MIN_NET_REWARD_R")
        ),
        cooldown_minutes=_parse_int(
            _get(env, prefix, "COOLDOWN_MINUTES", defaults), var("COOLDOWN_MINUTES")
        ),
        max_signals_per_session=_parse_int(
            _get(env, prefix, "MAX_SIGNALS_PER_SESSION", defaults), var("MAX_SIGNALS_PER_SESSION")
        ),
        setup_expiration_candles=_parse_int(
            _get(env, prefix, "SETUP_EXPIRATION_CANDLES", defaults),
            var("SETUP_EXPIRATION_CANDLES"),
        ),
    )
    _validate_breakout_continuation_config(config)
    return config


def _validate_breakout_continuation_config(c: BreakoutContinuationConfig) -> None:
    if c.level_lookback <= 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTCONTINUATION_LEVEL_LOOKBACK must be positive")
    if c.continuation_breakout_min_atr_multiple < 0:
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTCONTINUATION_CONTINUATION_BREAKOUT_MIN_ATR_MULTIPLE "
            "must not be negative"
        )
    if not (0 < c.continuation_min_body_ratio <= 1):
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTCONTINUATION_CONTINUATION_MIN_BODY_RATIO must be in (0, 1]"
        )
    if not (0 < c.continuation_close_position_ratio <= 0.5):
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTCONTINUATION_CONTINUATION_CLOSE_POSITION_RATIO must be in (0, 0.5]"
        )
    if c.continuation_max_range_atr_multiple <= 0:
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTCONTINUATION_CONTINUATION_MAX_RANGE_ATR_MULTIPLE must be positive"
        )
    if c.confirmation_tolerance_atr_fraction < 0:
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTCONTINUATION_CONFIRMATION_TOLERANCE_ATR_FRACTION "
            "must not be negative"
        )
    if not c.structure_lookbacks or any(lb <= 0 for lb in c.structure_lookbacks):
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTCONTINUATION_STRUCTURE_LOOKBACKS must be a "
            "non-empty list of positive ints"
        )
    if c.min_net_reward_r <= 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTCONTINUATION_MIN_NET_REWARD_R must be positive")
    if c.cooldown_minutes < 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTCONTINUATION_COOLDOWN_MINUTES must not be negative")
    if c.max_signals_per_session <= 0:
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTCONTINUATION_MAX_SIGNALS_PER_SESSION must be positive"
        )
    if c.setup_expiration_candles <= 0:
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTCONTINUATION_SETUP_EXPIRATION_CANDLES must be positive"
        )


# --- Orchestration ----------------------------------------------------------


def _min_required_candles(
    mode_config: ModeConfig, family_config: BreakoutContinuationConfig
) -> int:
    return (
        max(
            mode_config.atr_period,
            family_config.level_lookback + 2,  # +2: breakout and confirmation candles excluded
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
    total = len(conditions_met) + len(conditions_failed)
    confidence = (len(conditions_met) / total * 100.0) if total else 0.0
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
        confidence_score=confidence,
        reason=reason,
    )


def evaluate_breakout_continuation(
    *,
    mode: StrategyMode,
    version: str,
    mode_config: ModeConfig,
    family_config: BreakoutContinuationConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    now: datetime,
    context: EvaluationContext | None = None,
) -> StrategySignal:
    context = context or EvaluationContext()
    entry_timeframe = mode_config.entry_timeframe
    confirmation_timeframe = mode_config.confirmation_timeframe
    signal_timestamp = (
        entry_candles[-1].timestamp + entry_timeframe.duration if entry_candles else now
    )

    def no_trade(reason: str, met: list[str] | None = None, failed: list[str] | None = None):
        return _no_trade(
            mode=mode,
            version=version,
            instrument=instrument,
            entry_timeframe=entry_timeframe,
            confirmation_timeframe=confirmation_timeframe,
            signal_timestamp=signal_timestamp,
            conditions_met=met or [],
            conditions_failed=failed or [],
            reason=reason,
        )

    min_entry_candles = _min_required_candles(mode_config, family_config)
    if len(entry_candles) < min_entry_candles:
        return no_trade("insufficient_candle_history")

    if context.last_signal_time is not None:
        elapsed = now - context.last_signal_time
        if elapsed < timedelta(minutes=family_config.cooldown_minutes):
            return no_trade("cooldown_active")

    if context.signals_emitted_this_session >= family_config.max_signals_per_session:
        return no_trade("max_signals_per_session_reached")

    atr_vals = compute_atr(entry_candles, mode_config.atr_period)
    breakout_idx = len(entry_candles) - 2
    confirm_idx = len(entry_candles) - 1
    breakout_atr = atr_vals[breakout_idx]
    if breakout_atr is None:
        return no_trade("indicators_unavailable")

    # Level computed from candles strictly before both the breakout and
    # confirmation candles, so it can never be defined using the very
    # bars it's meant to predate.
    resistance, support = recent_swing_levels(
        entry_candles, family_config.level_lookback, exclude_last=2
    )
    if resistance is None and support is None:
        return no_trade("level_not_found", failed=["level_found"])

    breakout_candle = entry_candles[breakout_idx]
    confirmation_candle = entry_candles[confirm_idx]

    direction: SignalDirection | None = None
    level: float | None = None
    if resistance is not None and classify_breakout_candle(
        breakout_candle,
        level=resistance,
        direction=SignalDirection.BUY,
        atr=breakout_atr,
        config=family_config,
    ):
        direction, level = SignalDirection.BUY, resistance
    elif support is not None and classify_breakout_candle(
        breakout_candle,
        level=support,
        direction=SignalDirection.SELL,
        atr=breakout_atr,
        config=family_config,
    ):
        direction, level = SignalDirection.SELL, support

    if direction is None:
        return no_trade(
            "no_qualifying_breakout_candle",
            met=["level_found"],
            failed=["breakout_candle_qualified"],
        )
    met = ["level_found", "breakout_candle_qualified"]

    tolerance = family_config.confirmation_tolerance_atr_fraction * breakout_atr
    confirmed = classify_confirmation_candle(
        confirmation_candle,
        level=level,
        breakout_close=breakout_candle.close,
        direction=direction,
        tolerance=tolerance,
    )
    if not confirmed:
        return no_trade("breakout_not_confirmed", met=met, failed=["confirmation_candle_qualified"])
    met.append("confirmation_candle_qualified")

    entry_price = confirmation_candle.close
    structural_ref = support if direction == SignalDirection.BUY else resistance
    current_atr = atr_vals[confirm_idx] or breakout_atr
    stop_loss = compute_stop_loss(
        direction=direction,
        entry_price=entry_price,
        atr=current_atr,
        atr_stop_multiplier=mode_config.atr_stop_multiplier,
        structural_ref=structural_ref,
        tolerance=tolerance,
    )
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        return no_trade("invalid_risk_distance", met=met, failed=["sufficient_reward_after_costs"])

    costs = estimate_costs(
        mode_config.estimated_spread,
        mode_config.estimated_slippage,
        mode_config.estimated_transaction_cost,
    )
    candidate_levels = candidate_structure_levels(
        entry_candles, direction=direction, lookbacks=family_config.structure_lookbacks
    )
    targets: list[ProfitTarget] = build_targets(
        direction=direction,
        entry=entry_price,
        stop_loss=stop_loss,
        candidate_levels=candidate_levels,
        costs=costs,
        min_net_reward_r=family_config.min_net_reward_r,
        allow_tp3=True,
    )
    if not targets:
        return no_trade(
            "no_target_clears_minimum_net_reward_after_costs",
            met=met,
            failed=["sufficient_reward_after_costs"],
        )
    met.append("sufficient_reward_after_costs")

    setup_expiration = (
        signal_timestamp + family_config.setup_expiration_candles * entry_timeframe.duration
    )
    invalidation_conditions = [
        f"price closes back {'below' if direction == SignalDirection.BUY else 'above'} "
        f"the broken level {level:.2f} before entry is filled",
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
        f"{direction.value}: breakout beyond {level:.2f} confirmed by a further, "
        f"directional close within tolerance"
    )

    return StrategySignal(
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
        estimated_spread=mode_config.estimated_spread,
        estimated_slippage=mode_config.estimated_slippage,
        conditions_met=met,
        conditions_failed=[],
        confidence_score=confidence,
        reason=reason,
    )


class BreakoutContinuationStrategy:
    """`Strategy`-protocol wrapper, mirroring `TrendPullbackStrategy`'s
    shape exactly."""

    mode = StrategyMode.BREAKOUT_CONTINUATION
    version = STRATEGY_VERSION

    def __init__(
        self,
        mode_config: ModeConfig,
        family_config: BreakoutContinuationConfig,
        instrument: str,
    ):
        self.config = mode_config
        self.family_config = family_config
        self.instrument = instrument

    def evaluate(
        self,
        entry_candles: list[Candle],
        confirmation_candles: list[Candle],
        *,
        now: datetime,
        context: EvaluationContext | None = None,
    ) -> StrategySignal:
        return evaluate_breakout_continuation(
            mode=self.mode,
            version=self.version,
            mode_config=self.config,
            family_config=self.family_config,
            instrument=self.instrument,
            entry_candles=entry_candles,
            confirmation_candles=confirmation_candles,
            now=now,
            context=context,
        )
