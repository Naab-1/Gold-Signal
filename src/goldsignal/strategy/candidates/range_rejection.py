"""Range Rejection (STRATEGY RESEARCH AND REPLACEMENT program, Phase 4,
candidate Family D) -- see docs/phase4_range_rejection.md for the full
spec and reasoning.

Rule, in one sentence: within a genuine, bounded, non-trending range,
fade a touch of either boundary that closes back inside the range on a
directional candle -- BUY when support is tested and rejected upward,
SELL when resistance is tested and rejected downward.

Unlike Families A-C, this family's own spec requires the market to be
"objectively classified as ranging" -- the full 5-way TRENDING/RANGING/
HIGH_VOLATILITY/LOW_VOLATILITY/UNCERTAIN regime classifier is Phase 5's
job, not this one's. This module implements only the minimal,
family-specific check it actually needs: confirmation-timeframe EMA
fast/slow separation *below* a ceiling (the mirror image of Family A's
own "is there an established trend" floor check) plus a range whose
width is neither noise-thin nor too wide to treat its boundaries as
meaningful. The complete, benchmark-compared regime classifier is left
to its own future phase, exactly as Family A's simple EMA-separation
trend check was never promoted into a shared "trend classifier".

The rejection shape itself -- touch a level within tolerance, close back
out of it on a directional candle -- is geometrically the same test
Family C (`breakout_and_retest.py::is_retest_and_reject`) uses at a
*broken* level. This module keeps its own, independently-named copy
(`is_range_boundary_rejection`) rather than importing across candidate
families: each family is designed, tuned, and evaluated independently,
and importing one family's predicate into another would blur that line
even where the arithmetic happens to coincide. The precondition is what
actually differs -- Family C requires a prior qualifying breakout that
hasn't been invalidated; this family requires a validated, non-trending
range instead.

Fully stateless per call, matching the `Strategy` Protocol and
`analysis/candidate_walk.py`'s generic harness with zero modification,
same as Families A-C.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from goldsignal.config import ConfigError, ModeConfig, _get, _parse_float, _parse_int
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
from goldsignal.strategy.base import EvaluationContext, make_signal_id
from goldsignal.strategy.cost_model import estimate_costs
from goldsignal.strategy.stop_loss import compute_stop_loss
from goldsignal.strategy.targets import build_targets, candidate_structure_levels

STRATEGY_VERSION = "range_rejection_v1"

_ALL_CONDITIONS = (
    "range_identified",
    "range_width_valid",
    "not_trending",
    "rejection_confirmed",
    "sufficient_reward_after_costs",
)


# --- Family-specific config (own class, not added to ModeConfig -- see
# docs/phase4_range_rejection.md, following the convention established by
# every prior Phase 4 family) --------------------------------------------


@dataclass(frozen=True)
class RangeRejectionConfig:
    range_lookback: int
    min_range_width_atr_multiple: float
    max_range_width_atr_multiple: float
    max_trend_strength_atr_multiple: float
    rejection_tolerance_atr_fraction: float
    structure_lookbacks: tuple[int, ...]
    min_net_reward_r: float
    cooldown_minutes: int
    max_signals_per_session: int
    setup_expiration_candles: int


_RANGEREJECTION_DEFAULTS: dict[str, str] = {
    "RANGE_LOOKBACK": "20",
    "MIN_RANGE_WIDTH_ATR_MULTIPLE": "1.5",
    "MAX_RANGE_WIDTH_ATR_MULTIPLE": "6.0",
    "MAX_TREND_STRENGTH_ATR_MULTIPLE": "0.5",
    "REJECTION_TOLERANCE_ATR_FRACTION": "0.25",
    "STRUCTURE_LOOKBACKS": "20,40,60",
    "MIN_NET_REWARD_R": "1.5",
    "COOLDOWN_MINUTES": "60",
    "MAX_SIGNALS_PER_SESSION": "3",
    "SETUP_EXPIRATION_CANDLES": "3",
}


def load_range_rejection_config(env: Mapping[str, str] | None = None) -> RangeRejectionConfig:
    env = os.environ if env is None else env
    prefix = "RANGEREJECTION_"
    defaults = _RANGEREJECTION_DEFAULTS

    def var(name: str) -> str:
        return f"GOLDSIGNAL_{prefix}{name}"

    lookbacks_raw = _get(env, prefix, "STRUCTURE_LOOKBACKS", defaults)
    try:
        structure_lookbacks = tuple(int(x.strip()) for x in lookbacks_raw.split(","))
    except ValueError as exc:
        raise ConfigError(
            f"{var('STRUCTURE_LOOKBACKS')} must be a comma-separated int list"
        ) from exc

    config = RangeRejectionConfig(
        range_lookback=_parse_int(
            _get(env, prefix, "RANGE_LOOKBACK", defaults), var("RANGE_LOOKBACK")
        ),
        min_range_width_atr_multiple=_parse_float(
            _get(env, prefix, "MIN_RANGE_WIDTH_ATR_MULTIPLE", defaults),
            var("MIN_RANGE_WIDTH_ATR_MULTIPLE"),
        ),
        max_range_width_atr_multiple=_parse_float(
            _get(env, prefix, "MAX_RANGE_WIDTH_ATR_MULTIPLE", defaults),
            var("MAX_RANGE_WIDTH_ATR_MULTIPLE"),
        ),
        max_trend_strength_atr_multiple=_parse_float(
            _get(env, prefix, "MAX_TREND_STRENGTH_ATR_MULTIPLE", defaults),
            var("MAX_TREND_STRENGTH_ATR_MULTIPLE"),
        ),
        rejection_tolerance_atr_fraction=_parse_float(
            _get(env, prefix, "REJECTION_TOLERANCE_ATR_FRACTION", defaults),
            var("REJECTION_TOLERANCE_ATR_FRACTION"),
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
    _validate_range_rejection_config(config)
    return config


def _validate_range_rejection_config(c: RangeRejectionConfig) -> None:
    if c.range_lookback <= 0:
        raise ConfigError("GOLDSIGNAL_RANGEREJECTION_RANGE_LOOKBACK must be positive")
    if c.min_range_width_atr_multiple <= 0:
        raise ConfigError("GOLDSIGNAL_RANGEREJECTION_MIN_RANGE_WIDTH_ATR_MULTIPLE must be positive")
    if c.max_range_width_atr_multiple <= c.min_range_width_atr_multiple:
        raise ConfigError(
            "GOLDSIGNAL_RANGEREJECTION_MAX_RANGE_WIDTH_ATR_MULTIPLE must be greater than "
            "GOLDSIGNAL_RANGEREJECTION_MIN_RANGE_WIDTH_ATR_MULTIPLE"
        )
    if c.max_trend_strength_atr_multiple <= 0:
        raise ConfigError(
            "GOLDSIGNAL_RANGEREJECTION_MAX_TREND_STRENGTH_ATR_MULTIPLE must be positive"
        )
    if c.rejection_tolerance_atr_fraction < 0:
        raise ConfigError(
            "GOLDSIGNAL_RANGEREJECTION_REJECTION_TOLERANCE_ATR_FRACTION must not be negative"
        )
    if not c.structure_lookbacks or any(lb <= 0 for lb in c.structure_lookbacks):
        raise ConfigError(
            "GOLDSIGNAL_RANGEREJECTION_STRUCTURE_LOOKBACKS must be a "
            "non-empty list of positive ints"
        )
    if c.min_net_reward_r <= 0:
        raise ConfigError("GOLDSIGNAL_RANGEREJECTION_MIN_NET_REWARD_R must be positive")
    if c.cooldown_minutes < 0:
        raise ConfigError("GOLDSIGNAL_RANGEREJECTION_COOLDOWN_MINUTES must not be negative")
    if c.max_signals_per_session <= 0:
        raise ConfigError("GOLDSIGNAL_RANGEREJECTION_MAX_SIGNALS_PER_SESSION must be positive")
    if c.setup_expiration_candles <= 0:
        raise ConfigError("GOLDSIGNAL_RANGEREJECTION_SETUP_EXPIRATION_CANDLES must be positive")


# --- Pure predicates -------------------------------------------------------


def is_valid_range_width(
    *, resistance: float, support: float, atr: float, min_multiple: float, max_multiple: float
) -> bool:
    """True if the range's width, expressed in ATR terms, is wide enough
    to be a real range (not noise) and narrow enough that its boundaries
    are still meaningfully bounded (not so wide the "range" is really an
    untrended drift with no tradeable edges).
    """
    width = resistance - support
    if width <= 0:
        return False
    return min_multiple * atr <= width <= max_multiple * atr


def is_ranging_market(
    *,
    confirm_ema_fast: float,
    confirm_ema_slow: float,
    confirm_atr: float,
    max_trend_strength_atr_multiple: float,
) -> bool:
    """The mirror image of Family A's `is_established_trend` -- ranging
    means the confirmation-timeframe EMA fast/slow separation stays
    *below* a ceiling, rather than *at/beyond* a floor. Directly
    implements this family's own "do not use it during a strong trend"
    requirement without invoking a full regime classifier.
    """
    separation = abs(confirm_ema_fast - confirm_ema_slow)
    return separation < max_trend_strength_atr_multiple * confirm_atr


def is_range_boundary_rejection(
    candle: Candle, *, level: float, direction: SignalDirection, tolerance: float
) -> bool:
    """True if `candle` touches `level` (within `tolerance`) and closes
    back inside the range on a directional candle -- BUY when support is
    touched and rejected upward, SELL when resistance is touched and
    rejected downward.
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


def _min_required_candles(mode_config: ModeConfig, family_config: RangeRejectionConfig) -> int:
    return (
        max(
            mode_config.atr_period,
            family_config.range_lookback + 1,
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


def evaluate_range_rejection(
    *,
    mode: StrategyMode,
    version: str,
    mode_config: ModeConfig,
    family_config: RangeRejectionConfig,
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
    min_confirm_candles = mode_config.ema_slow_period + 1
    if len(entry_candles) < min_entry_candles or len(confirmation_candles) < min_confirm_candles:
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

    confirm_closes = [c.close for c in confirmation_candles]
    confirm_ema_fast_vals = compute_ema(confirm_closes, mode_config.ema_fast_period)
    confirm_ema_slow_vals = compute_ema(confirm_closes, mode_config.ema_slow_period)
    confirm_atr_vals = compute_atr(confirmation_candles, mode_config.atr_period)

    if (
        current_atr is None
        or confirm_ema_fast_vals[-1] is None
        or confirm_ema_slow_vals[-1] is None
        or confirm_atr_vals[-1] is None
    ):
        return no_trade("indicators_unavailable")

    resistance, support = recent_swing_levels(entry_candles, family_config.range_lookback)
    if resistance is None or support is None:
        return no_trade("range_not_found", failed=["range_identified"])
    met = ["range_identified"]

    if not is_valid_range_width(
        resistance=resistance,
        support=support,
        atr=current_atr,
        min_multiple=family_config.min_range_width_atr_multiple,
        max_multiple=family_config.max_range_width_atr_multiple,
    ):
        return no_trade("range_width_out_of_bounds", met=met, failed=["range_width_valid"])
    met.append("range_width_valid")

    if not is_ranging_market(
        confirm_ema_fast=confirm_ema_fast_vals[-1],
        confirm_ema_slow=confirm_ema_slow_vals[-1],
        confirm_atr=confirm_atr_vals[-1],
        max_trend_strength_atr_multiple=family_config.max_trend_strength_atr_multiple,
    ):
        return no_trade("market_trending_too_strongly", met=met, failed=["not_trending"])
    met.append("not_trending")

    current_candle = entry_candles[current_idx]
    tolerance = family_config.rejection_tolerance_atr_fraction * current_atr

    for direction, level in ((SignalDirection.BUY, support), (SignalDirection.SELL, resistance)):
        if not is_range_boundary_rejection(
            current_candle, level=level, direction=direction, tolerance=tolerance
        ):
            continue

        entry_price = current_candle.close
        stop_loss = compute_stop_loss(
            direction=direction,
            entry_price=entry_price,
            atr=current_atr,
            atr_stop_multiplier=mode_config.atr_stop_multiplier,
            structural_ref=level,
            tolerance=tolerance,
        )
        risk = abs(entry_price - stop_loss)
        if risk <= 0:
            return no_trade(
                "invalid_risk_distance",
                met=met + ["rejection_confirmed"],
                failed=["sufficient_reward_after_costs"],
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
                met=met + ["rejection_confirmed"],
                failed=["sufficient_reward_after_costs"],
            )

        setup_expiration = (
            signal_timestamp + family_config.setup_expiration_candles * entry_timeframe.duration
        )
        invalidation_conditions = [
            f"price closes back {'below' if direction == SignalDirection.BUY else 'above'} "
            f"the rejected boundary {level:.2f} before entry is filled",
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
        final_met = met + ["rejection_confirmed", "sufficient_reward_after_costs"]
        confidence = len(final_met) / len(_ALL_CONDITIONS) * 100.0
        reason = (
            f"{direction.value}: rejection of range boundary {level:.2f} within a "
            f"validated, non-trending range"
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
            conditions_met=final_met,
            conditions_failed=[],
            confidence_score=confidence,
            reason=reason,
        )

    return no_trade(
        "no_boundary_rejection_confirmed_either_direction",
        met=met,
        failed=["rejection_confirmed"],
    )


class RangeRejectionStrategy:
    """`Strategy`-protocol wrapper, mirroring Families A-C's shape exactly."""

    mode = StrategyMode.RANGE_REJECTION
    version = STRATEGY_VERSION

    def __init__(
        self,
        mode_config: ModeConfig,
        family_config: RangeRejectionConfig,
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
        return evaluate_range_rejection(
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
