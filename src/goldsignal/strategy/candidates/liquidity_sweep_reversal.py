"""Liquidity Sweep and Reversal (STRATEGY RESEARCH AND REPLACEMENT
program, Phase 4, candidate Family E) -- see
docs/phase4_liquidity_sweep_reversal.md for the full spec and reasoning.

Per the user's own instruction, this family must be "mathematically
defined... no vague visual or smart-money terminology". "Liquidity
sweep" here means exactly one thing, checkable from OHLC alone: a
single candle whose high (or low) exceeds a prior swing extreme by a
meaningful margin, then closes back beyond that same level by a
meaningful margin, on a directional candle. Nothing about "smart money",
order blocks, or intent is encoded or needed -- this is a specific,
falsifiable candle shape (a long wick beyond a level followed by a
decisive close back through it), not a narrative.

Deliberately distinct from Family C (Breakout and Retest) and Family D
(Range Rejection), both of which this shape superficially resembles:
- Family C requires a prior candle to *qualify* as a strong breakout
  (`classify_breakout_candle`: large body, closes near its extreme) and
  then, on a LATER candle, a separate retest-and-reject. The breakout
  itself succeeds; only the retest fails.
- Family D requires the market to first be validated as a bounded,
  non-trending range, and the boundary is never actually broken -- price
  only wicks within tolerance of it.
- Family E requires neither a prior qualifying breakout candle nor a
  non-trending precondition. It looks for the level being broken and
  failing within the SAME candle: a single-candle overshoot-then-reverse,
  which is what a genuine stop-run/liquidity-sweep candle looks like on
  a chart, expressed here as three OHLC-only numeric conditions.

Fully stateless per call, matching the `Strategy` Protocol and
`analysis/candidate_walk.py`'s generic harness with zero modification,
same as Families A-D. `confirmation_candles` is accepted (required by
the `Strategy` Protocol) but not used for any indicator computation --
this family's mechanics are entirely single-timeframe, the same
precedent Family B (Breakout Continuation) already established.
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
from goldsignal.strategy.cost_model import estimate_costs
from goldsignal.strategy.stop_loss import compute_stop_loss
from goldsignal.strategy.targets import build_targets, candidate_structure_levels

STRATEGY_VERSION = "liquidity_sweep_reversal_v1"

_ALL_CONDITIONS = (
    "level_found",
    "sweep_and_reversal_confirmed",
    "sufficient_reward_after_costs",
)


# --- Family-specific config (own class, not added to ModeConfig -- see
# docs/phase4_liquidity_sweep_reversal.md, following the convention
# established by every prior Phase 4 family) ------------------------------


@dataclass(frozen=True)
class LiquiditySweepReversalConfig:
    sweep_lookback: int
    sweep_min_atr_multiple: float
    reversal_min_atr_multiple: float
    stop_buffer_atr_fraction: float
    structure_lookbacks: tuple[int, ...]
    min_net_reward_r: float
    cooldown_minutes: int
    max_signals_per_session: int
    setup_expiration_candles: int


_LIQUIDITYSWEEPREVERSAL_DEFAULTS: dict[str, str] = {
    "SWEEP_LOOKBACK": "20",
    "SWEEP_MIN_ATR_MULTIPLE": "0.15",
    "REVERSAL_MIN_ATR_MULTIPLE": "0.10",
    "STOP_BUFFER_ATR_FRACTION": "0.15",
    "STRUCTURE_LOOKBACKS": "20,40,60",
    "MIN_NET_REWARD_R": "1.5",
    "COOLDOWN_MINUTES": "30",
    "MAX_SIGNALS_PER_SESSION": "4",
    "SETUP_EXPIRATION_CANDLES": "3",
}


def load_liquidity_sweep_reversal_config(
    env: Mapping[str, str] | None = None,
) -> LiquiditySweepReversalConfig:
    env = os.environ if env is None else env
    prefix = "LIQUIDITYSWEEPREVERSAL_"
    defaults = _LIQUIDITYSWEEPREVERSAL_DEFAULTS

    def var(name: str) -> str:
        return f"GOLDSIGNAL_{prefix}{name}"

    lookbacks_raw = _get(env, prefix, "STRUCTURE_LOOKBACKS", defaults)
    try:
        structure_lookbacks = tuple(int(x.strip()) for x in lookbacks_raw.split(","))
    except ValueError as exc:
        raise ConfigError(
            f"{var('STRUCTURE_LOOKBACKS')} must be a comma-separated int list"
        ) from exc

    config = LiquiditySweepReversalConfig(
        sweep_lookback=_parse_int(
            _get(env, prefix, "SWEEP_LOOKBACK", defaults), var("SWEEP_LOOKBACK")
        ),
        sweep_min_atr_multiple=_parse_float(
            _get(env, prefix, "SWEEP_MIN_ATR_MULTIPLE", defaults), var("SWEEP_MIN_ATR_MULTIPLE")
        ),
        reversal_min_atr_multiple=_parse_float(
            _get(env, prefix, "REVERSAL_MIN_ATR_MULTIPLE", defaults),
            var("REVERSAL_MIN_ATR_MULTIPLE"),
        ),
        stop_buffer_atr_fraction=_parse_float(
            _get(env, prefix, "STOP_BUFFER_ATR_FRACTION", defaults),
            var("STOP_BUFFER_ATR_FRACTION"),
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
    _validate_liquidity_sweep_reversal_config(config)
    return config


def _validate_liquidity_sweep_reversal_config(c: LiquiditySweepReversalConfig) -> None:
    if c.sweep_lookback <= 0:
        raise ConfigError("GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_SWEEP_LOOKBACK must be positive")
    if c.sweep_min_atr_multiple <= 0:
        raise ConfigError(
            "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_SWEEP_MIN_ATR_MULTIPLE must be positive"
        )
    if c.reversal_min_atr_multiple <= 0:
        raise ConfigError(
            "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_REVERSAL_MIN_ATR_MULTIPLE must be positive"
        )
    if c.stop_buffer_atr_fraction < 0:
        raise ConfigError(
            "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_STOP_BUFFER_ATR_FRACTION must not be negative"
        )
    if not c.structure_lookbacks or any(lb <= 0 for lb in c.structure_lookbacks):
        raise ConfigError(
            "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_STRUCTURE_LOOKBACKS must be a "
            "non-empty list of positive ints"
        )
    if c.min_net_reward_r <= 0:
        raise ConfigError("GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_MIN_NET_REWARD_R must be positive")
    if c.cooldown_minutes < 0:
        raise ConfigError("GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_COOLDOWN_MINUTES must not be negative")
    if c.max_signals_per_session <= 0:
        raise ConfigError(
            "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_MAX_SIGNALS_PER_SESSION must be positive"
        )
    if c.setup_expiration_candles <= 0:
        raise ConfigError(
            "GOLDSIGNAL_LIQUIDITYSWEEPREVERSAL_SETUP_EXPIRATION_CANDLES must be positive"
        )


# --- Pure predicates -------------------------------------------------------


def is_liquidity_sweep_reversal(
    candle: Candle,
    *,
    level: float,
    direction: SignalDirection,
    sweep_min_distance: float,
    reversal_min_distance: float,
) -> bool:
    """True if `candle` exceeds `level` by at least `sweep_min_distance`
    (a genuine overshoot beyond the prior swing extreme, not noise) and
    then closes back beyond `level` by at least `reversal_min_distance`
    (a decisive reversal, not a bare graze) on a directional candle --
    all within this single candle. SELL sweeps a swing high (resistance)
    and reverses down; BUY sweeps a swing low (support) and reverses up.
    """
    is_sell = direction == SignalDirection.SELL
    if is_sell:
        swept = candle.high >= level + sweep_min_distance
        reversed_back = candle.close <= level - reversal_min_distance
        directional = candle.close < candle.open
    else:
        swept = candle.low <= level - sweep_min_distance
        reversed_back = candle.close >= level + reversal_min_distance
        directional = candle.close > candle.open
    return swept and reversed_back and directional


# --- Orchestration ----------------------------------------------------------


def _min_required_candles(
    mode_config: ModeConfig, family_config: LiquiditySweepReversalConfig
) -> int:
    return (
        max(
            mode_config.atr_period,
            family_config.sweep_lookback + 1,
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


def evaluate_liquidity_sweep_reversal(
    *,
    mode: StrategyMode,
    version: str,
    mode_config: ModeConfig,
    family_config: LiquiditySweepReversalConfig,
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

    resistance, support = recent_swing_levels(entry_candles, family_config.sweep_lookback)
    if resistance is None or support is None:
        return no_trade("level_not_found", failed=["level_found"])
    met = ["level_found"]

    current_candle = entry_candles[current_idx]
    sweep_min_distance = family_config.sweep_min_atr_multiple * current_atr
    reversal_min_distance = family_config.reversal_min_atr_multiple * current_atr
    stop_buffer = family_config.stop_buffer_atr_fraction * current_atr

    for direction, level in ((SignalDirection.SELL, resistance), (SignalDirection.BUY, support)):
        if not is_liquidity_sweep_reversal(
            current_candle,
            level=level,
            direction=direction,
            sweep_min_distance=sweep_min_distance,
            reversal_min_distance=reversal_min_distance,
        ):
            continue

        entry_price = current_candle.close
        swept_extreme = (
            current_candle.high if direction == SignalDirection.SELL else current_candle.low
        )
        stop_loss = compute_stop_loss(
            direction=direction,
            entry_price=entry_price,
            atr=current_atr,
            atr_stop_multiplier=mode_config.atr_stop_multiplier,
            structural_ref=swept_extreme,
            tolerance=stop_buffer,
        )
        risk = abs(entry_price - stop_loss)
        if risk <= 0:
            return no_trade(
                "invalid_risk_distance",
                met=met + ["sweep_and_reversal_confirmed"],
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
                met=met + ["sweep_and_reversal_confirmed"],
                failed=["sufficient_reward_after_costs"],
            )

        setup_expiration = (
            signal_timestamp + family_config.setup_expiration_candles * entry_timeframe.duration
        )
        invalidation_conditions = [
            f"price re-exceeds the swept extreme {swept_extreme:.2f} before entry is filled",
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
        final_met = met + ["sweep_and_reversal_confirmed", "sufficient_reward_after_costs"]
        confidence = len(final_met) / len(_ALL_CONDITIONS) * 100.0
        reason = (
            f"{direction.value}: liquidity sweep of {level:.2f} reversed with a decisive "
            f"directional close back through the level"
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
        "no_sweep_and_reversal_confirmed_either_direction",
        met=met,
        failed=["sweep_and_reversal_confirmed"],
    )


class LiquiditySweepReversalStrategy:
    """`Strategy`-protocol wrapper, mirroring Families A-D's shape exactly."""

    mode = StrategyMode.LIQUIDITY_SWEEP_REVERSAL
    version = STRATEGY_VERSION

    def __init__(
        self,
        mode_config: ModeConfig,
        family_config: LiquiditySweepReversalConfig,
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
        return evaluate_liquidity_sweep_reversal(
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
