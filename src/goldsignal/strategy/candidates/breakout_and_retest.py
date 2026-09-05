"""Breakout and Retest (STRATEGY RESEARCH AND REPLACEMENT program, Phase 4,
candidate Family C) -- see docs/phase4_breakout_and_retest.md for the full
spec and reasoning.

Per the user's own instruction: "Preserve as a highly selective candidate.
Do not assume it is automatically superior." This matters here more than
for any other family, because the *frozen, rejected* A+ baseline
(strategy/_common.py) also used a breakout-and-retest confirmation --
mixed together with its own EMA/RSI trend filters, which may well be why
it failed, not the breakout-and-retest concept itself. This module is a
genuinely fresh, independently-tuned candidate: its own config, own
timeframes, own thresholds, its own selectivity rules -- not a repackage
of the rejected rule under a new name, which would prove nothing.

Reuses the frozen `strategy/continuation.py::classify_breakout_candle`
UNCHANGED for the breakout candle's own strength check (the same
already-tested "is this a real breakout, not a weak one" arithmetic
Family B also reuses) -- but the confirmation shape here is deliberately
different from both the old A+ rule and Family B: instead of requiring
immediate further movement (Family B) or a fixed retest-then-continue
scan (the old A+ rule's `indicators/structure.py::breakout_and_retest`,
left untouched and unused here), this family requires the *current*
candle itself to be a retest-and-reject candle -- wicking back into the
level and closing back out of it directionally -- with every candle
between the breakout and now checked to confirm the level was never
already closed through (which would invalidate the setup, not "retest"
it).

Fully stateless per call, matching the `Strategy` Protocol and
`analysis/candidate_walk.py`'s generic harness with zero modification,
same as Families A and B.
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
from goldsignal.strategy.continuation import classify_breakout_candle
from goldsignal.strategy.cost_model import estimate_costs
from goldsignal.strategy.stop_loss import compute_stop_loss
from goldsignal.strategy.targets import build_targets, candidate_structure_levels

STRATEGY_VERSION = "breakout_and_retest_v1"

_ALL_CONDITIONS = (
    "level_found",
    "breakout_candle_qualified",
    "not_invalidated_before_retest",
    "retest_and_reject_confirmed",
    "sufficient_reward_after_costs",
)


# --- Family-specific config ---------------------------------------------


@dataclass(frozen=True)
class BreakoutAndRetestConfig:
    level_lookback: int
    retest_lookback_candles: int
    # Field names below match strategy/continuation.py::classify_breakout_candle's
    # expected config attribute names, so this object can be passed
    # directly to that frozen, unmodified function.
    continuation_breakout_min_atr_multiple: float
    continuation_min_body_ratio: float
    continuation_close_position_ratio: float
    continuation_max_range_atr_multiple: float
    retest_tolerance_atr_fraction: float
    structure_lookbacks: tuple[int, ...]
    min_net_reward_r: float
    cooldown_minutes: int
    max_signals_per_session: int
    setup_expiration_candles: int


_BREAKOUTANDRETEST_DEFAULTS: dict[str, str] = {
    "LEVEL_LOOKBACK": "20",
    "RETEST_LOOKBACK_CANDLES": "20",
    "CONTINUATION_BREAKOUT_MIN_ATR_MULTIPLE": "0.10",
    "CONTINUATION_MIN_BODY_RATIO": "0.60",
    "CONTINUATION_CLOSE_POSITION_RATIO": "0.25",
    "CONTINUATION_MAX_RANGE_ATR_MULTIPLE": "2.0",
    "RETEST_TOLERANCE_ATR_FRACTION": "0.25",
    "STRUCTURE_LOOKBACKS": "20,40,60",
    "MIN_NET_REWARD_R": "1.5",
    "COOLDOWN_MINUTES": "60",
    "MAX_SIGNALS_PER_SESSION": "3",
    "SETUP_EXPIRATION_CANDLES": "3",
}


def load_breakout_and_retest_config(
    env: Mapping[str, str] | None = None,
) -> BreakoutAndRetestConfig:
    env = os.environ if env is None else env
    prefix = "BREAKOUTANDRETEST_"
    defaults = _BREAKOUTANDRETEST_DEFAULTS

    def var(name: str) -> str:
        return f"GOLDSIGNAL_{prefix}{name}"

    lookbacks_raw = _get(env, prefix, "STRUCTURE_LOOKBACKS", defaults)
    try:
        structure_lookbacks = tuple(int(x.strip()) for x in lookbacks_raw.split(","))
    except ValueError as exc:
        raise ConfigError(
            f"{var('STRUCTURE_LOOKBACKS')} must be a comma-separated int list"
        ) from exc

    config = BreakoutAndRetestConfig(
        level_lookback=_parse_int(
            _get(env, prefix, "LEVEL_LOOKBACK", defaults), var("LEVEL_LOOKBACK")
        ),
        retest_lookback_candles=_parse_int(
            _get(env, prefix, "RETEST_LOOKBACK_CANDLES", defaults), var("RETEST_LOOKBACK_CANDLES")
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
        retest_tolerance_atr_fraction=_parse_float(
            _get(env, prefix, "RETEST_TOLERANCE_ATR_FRACTION", defaults),
            var("RETEST_TOLERANCE_ATR_FRACTION"),
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
    _validate_breakout_and_retest_config(config)
    return config


def _validate_breakout_and_retest_config(c: BreakoutAndRetestConfig) -> None:
    if c.level_lookback <= 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTANDRETEST_LEVEL_LOOKBACK must be positive")
    if c.retest_lookback_candles <= 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTANDRETEST_RETEST_LOOKBACK_CANDLES must be positive")
    if c.continuation_breakout_min_atr_multiple < 0:
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTANDRETEST_CONTINUATION_BREAKOUT_MIN_ATR_MULTIPLE "
            "must not be negative"
        )
    if not (0 < c.continuation_min_body_ratio <= 1):
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTANDRETEST_CONTINUATION_MIN_BODY_RATIO must be in (0, 1]"
        )
    if not (0 < c.continuation_close_position_ratio <= 0.5):
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTANDRETEST_CONTINUATION_CLOSE_POSITION_RATIO must be in (0, 0.5]"
        )
    if c.continuation_max_range_atr_multiple <= 0:
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTANDRETEST_CONTINUATION_MAX_RANGE_ATR_MULTIPLE must be positive"
        )
    if c.retest_tolerance_atr_fraction < 0:
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTANDRETEST_RETEST_TOLERANCE_ATR_FRACTION must not be negative"
        )
    if not c.structure_lookbacks or any(lb <= 0 for lb in c.structure_lookbacks):
        raise ConfigError(
            "GOLDSIGNAL_BREAKOUTANDRETEST_STRUCTURE_LOOKBACKS must be a "
            "non-empty list of positive ints"
        )
    if c.min_net_reward_r <= 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTANDRETEST_MIN_NET_REWARD_R must be positive")
    if c.cooldown_minutes < 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTANDRETEST_COOLDOWN_MINUTES must not be negative")
    if c.max_signals_per_session <= 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTANDRETEST_MAX_SIGNALS_PER_SESSION must be positive")
    if c.setup_expiration_candles <= 0:
        raise ConfigError("GOLDSIGNAL_BREAKOUTANDRETEST_SETUP_EXPIRATION_CANDLES must be positive")


# --- Pure predicates -------------------------------------------------------


def find_qualifying_breakout_index(
    entry_candles: list[Candle],
    atr_vals: list[float | None],
    *,
    level: float,
    direction: SignalDirection,
    current_idx: int,
    lookback_candles: int,
    family_config: BreakoutAndRetestConfig,
) -> int | None:
    """The most recent candle (strictly before `current_idx`, within
    `lookback_candles`) that qualifies as a strong breakout candle against
    `level` -- reusing the frozen, already-tested
    `classify_breakout_candle` for the strength check.
    """
    earliest = max(0, current_idx - lookback_candles)
    for i in range(current_idx - 1, earliest - 1, -1):
        candle_atr = atr_vals[i]
        if candle_atr is None:
            continue
        if classify_breakout_candle(
            entry_candles[i], level=level, direction=direction, atr=candle_atr, config=family_config
        ):
            return i
    return None


def is_invalidated_before_retest(
    entry_candles: list[Candle],
    *,
    level: float,
    direction: SignalDirection,
    breakout_idx: int,
    current_idx: int,
) -> bool:
    """True if any candle strictly between the breakout and now already
    closed back through the level -- a genuine retest holds beyond the
    level throughout, only wicking into it at the retest candle itself;
    a candle that already closed back through means the breakout failed,
    not that it's mid-retest.
    """
    is_buy = direction == SignalDirection.BUY
    for i in range(breakout_idx + 1, current_idx):
        candle = entry_candles[i]
        closed_through = candle.close <= level if is_buy else candle.close >= level
        if closed_through:
            return True
    return False


def is_retest_and_reject(
    candle: Candle, *, level: float, direction: SignalDirection, tolerance: float
) -> bool:
    """True if `candle` wicks back into the level (within `tolerance`)
    but closes back out of it directionally -- a rejection candle at the
    retested level, not a new-high/low continuation (Family B's shape).
    """
    is_buy = direction == SignalDirection.BUY
    if is_buy:
        touched = candle.low <= level + tolerance
        rejected = candle.close > level + tolerance
        directional = candle.close > candle.open
    else:
        touched = candle.high >= level - tolerance
        rejected = candle.close < level - tolerance
        directional = candle.close < candle.open
    return touched and rejected and directional


# --- Orchestration ----------------------------------------------------------


def _min_required_candles(mode_config: ModeConfig, family_config: BreakoutAndRetestConfig) -> int:
    return (
        max(
            mode_config.atr_period,
            family_config.level_lookback + family_config.retest_lookback_candles + 1,
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


def evaluate_breakout_and_retest(
    *,
    mode: StrategyMode,
    version: str,
    mode_config: ModeConfig,
    family_config: BreakoutAndRetestConfig,
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
    current_idx = len(entry_candles) - 1
    current_atr = atr_vals[current_idx]
    if current_atr is None:
        return no_trade("indicators_unavailable")

    # Level computed strictly before the entire breakout+retest scan window.
    scan_span = family_config.retest_lookback_candles
    resistance, support = recent_swing_levels(
        entry_candles, family_config.level_lookback, exclude_last=scan_span
    )
    if resistance is None and support is None:
        return no_trade("level_not_found", failed=["level_found"])

    current_candle = entry_candles[current_idx]

    # Tracks the furthest-progressed failure across both directions, so the
    # final NO_TRADE (if neither direction fully qualifies) reports the
    # specific stage reached rather than one blanket "no setup" reason.
    best_reason = "no_breakout_candle_found_either_direction"
    best_met: list[str] = ["level_found"]
    best_failed: list[str] = ["breakout_candle_qualified"]

    for direction, level in ((SignalDirection.BUY, resistance), (SignalDirection.SELL, support)):
        if level is None:
            continue
        breakout_idx = find_qualifying_breakout_index(
            entry_candles,
            atr_vals,
            level=level,
            direction=direction,
            current_idx=current_idx,
            lookback_candles=scan_span,
            family_config=family_config,
        )
        if breakout_idx is None:
            continue
        met = ["level_found", "breakout_candle_qualified"]
        if len(met) > len(best_met):
            best_reason = "breakout_found_but_not_yet_retested"
            best_met, best_failed = met, ["not_invalidated_before_retest"]

        if is_invalidated_before_retest(
            entry_candles,
            level=level,
            direction=direction,
            breakout_idx=breakout_idx,
            current_idx=current_idx,
        ):
            if len(met) >= len(best_met):
                best_reason = "breakout_invalidated_before_retest"
                best_met, best_failed = met, ["not_invalidated_before_retest"]
            continue
        met.append("not_invalidated_before_retest")
        if len(met) > len(best_met):
            best_reason = "breakout_confirmed_but_retest_not_yet_rejected"
            best_met, best_failed = met, ["retest_and_reject_confirmed"]

        tolerance = family_config.retest_tolerance_atr_fraction * current_atr
        if not is_retest_and_reject(
            current_candle, level=level, direction=direction, tolerance=tolerance
        ):
            continue
        met.append("retest_and_reject_confirmed")

        # Found a fully-qualifying setup for this direction.
        entry_price = current_candle.close
        opposite_level = support if direction == SignalDirection.BUY else resistance
        stop_loss = compute_stop_loss(
            direction=direction,
            entry_price=entry_price,
            atr=current_atr,
            atr_stop_multiplier=mode_config.atr_stop_multiplier,
            structural_ref=opposite_level,
            tolerance=tolerance,
        )
        risk = abs(entry_price - stop_loss)
        if risk <= 0:
            return no_trade(
                "invalid_risk_distance", met=met, failed=["sufficient_reward_after_costs"]
            )

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
            f"the retested level {level:.2f} before entry is filled",
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
            f"{direction.value}: retest of {level:.2f} rejected with a directional close "
            f"after a qualifying breakout"
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

    return no_trade(best_reason, met=best_met, failed=best_failed)


class BreakoutAndRetestStrategy:
    """`Strategy`-protocol wrapper, mirroring Families A/B's shape exactly."""

    mode = StrategyMode.BREAKOUT_AND_RETEST
    version = STRATEGY_VERSION

    def __init__(
        self,
        mode_config: ModeConfig,
        family_config: BreakoutAndRetestConfig,
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
        return evaluate_breakout_and_retest(
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
