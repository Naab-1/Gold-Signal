"""Trend Pullback (STRATEGY RESEARCH AND REPLACEMENT program, Phase 4,
candidate Family A) -- see docs/phase4_trend_pullback.md for the full
spec, numeric-default reasoning, and the three mechanics gaps found and
fixed during design review.

Independent of, and never combined with, the frozen A+/A tiers
(strategy/_common.py, strategy/classification.py) -- this is a fresh
candidate, not a variant layered on top of the rejected baseline.

Rule, in one sentence: within an established higher-timeframe trend, find
the most recent RSI dip into a pullback, wait for the *first* candle after
that dip to reclaim both momentum (RSI cross) and price (close beyond the
fast EMA) in a directional (bullish/bearish) close, and reject the entry
if price is already extended beyond either the EMA or the pullback's own
structure.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from goldsignal.config import ConfigError, ModeConfig, _get, _parse_float, _parse_int
from goldsignal.indicators.atr import atr as compute_atr
from goldsignal.indicators.ema import ema as compute_ema
from goldsignal.indicators.rsi import rsi as compute_rsi
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

logger = logging.getLogger(__name__)

STRATEGY_VERSION = "trend_pullback_v1"

_ALL_CONDITIONS = (
    "trend_established",
    "pullback_dip_found",
    "rsi_first_crossing",
    "directional_close",
    "ema_reclaimed",
    "not_extended",
    "sufficient_reward_after_costs",
)


# --- Family-specific config (deliberately NOT added to ModeConfig -- see
# docs/phase4_trend_pullback.md's "config architecture" section) ---------


@dataclass(frozen=True)
class TrendPullbackConfig:
    trend_strength_atr_multiple: float
    pullback_rsi_trigger: float
    pullback_rsi_confirm: float
    pullback_lookback_candles: int
    max_extension_atr_multiple: float
    structure_lookbacks: tuple[int, ...]
    min_net_reward_r: float
    cooldown_minutes: int
    max_signals_per_session: int
    setup_expiration_candles: int


_TRENDPULLBACK_DEFAULTS: dict[str, str] = {
    "TREND_STRENGTH_ATR_MULTIPLE": "1.0",
    "PULLBACK_RSI_TRIGGER": "40",
    "PULLBACK_RSI_CONFIRM": "50",
    "PULLBACK_LOOKBACK_CANDLES": "20",
    "MAX_EXTENSION_ATR_MULTIPLE": "1.5",
    "STRUCTURE_LOOKBACKS": "20,40,60",
    "MIN_NET_REWARD_R": "1.5",
    "COOLDOWN_MINUTES": "60",
    "MAX_SIGNALS_PER_SESSION": "3",
    "SETUP_EXPIRATION_CANDLES": "3",
}


def load_trend_pullback_config(env: Mapping[str, str] | None = None) -> TrendPullbackConfig:
    env = os.environ if env is None else env
    prefix = "TRENDPULLBACK_"
    defaults = _TRENDPULLBACK_DEFAULTS

    def var(name: str) -> str:
        return f"GOLDSIGNAL_{prefix}{name}"

    lookbacks_raw = _get(env, prefix, "STRUCTURE_LOOKBACKS", defaults)
    try:
        structure_lookbacks = tuple(int(x.strip()) for x in lookbacks_raw.split(","))
    except ValueError as exc:
        raise ConfigError(
            f"{var('STRUCTURE_LOOKBACKS')} must be a comma-separated int list"
        ) from exc

    config = TrendPullbackConfig(
        trend_strength_atr_multiple=_parse_float(
            _get(env, prefix, "TREND_STRENGTH_ATR_MULTIPLE", defaults),
            var("TREND_STRENGTH_ATR_MULTIPLE"),
        ),
        pullback_rsi_trigger=_parse_float(
            _get(env, prefix, "PULLBACK_RSI_TRIGGER", defaults), var("PULLBACK_RSI_TRIGGER")
        ),
        pullback_rsi_confirm=_parse_float(
            _get(env, prefix, "PULLBACK_RSI_CONFIRM", defaults), var("PULLBACK_RSI_CONFIRM")
        ),
        pullback_lookback_candles=_parse_int(
            _get(env, prefix, "PULLBACK_LOOKBACK_CANDLES", defaults),
            var("PULLBACK_LOOKBACK_CANDLES"),
        ),
        max_extension_atr_multiple=_parse_float(
            _get(env, prefix, "MAX_EXTENSION_ATR_MULTIPLE", defaults),
            var("MAX_EXTENSION_ATR_MULTIPLE"),
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
    _validate_trend_pullback_config(config)
    return config


def _validate_trend_pullback_config(c: TrendPullbackConfig) -> None:
    if c.trend_strength_atr_multiple <= 0:
        raise ConfigError("GOLDSIGNAL_TRENDPULLBACK_TREND_STRENGTH_ATR_MULTIPLE must be positive")
    if not (0 < c.pullback_rsi_trigger < 50):
        raise ConfigError(
            "GOLDSIGNAL_TRENDPULLBACK_PULLBACK_RSI_TRIGGER must be between 0 and 50 (exclusive) "
            "-- it's a counter-trend dip threshold, mirrored to 100-trigger for downtrends"
        )
    if not (50 <= c.pullback_rsi_confirm < 100):
        raise ConfigError(
            "GOLDSIGNAL_TRENDPULLBACK_PULLBACK_RSI_CONFIRM must be between 50 and 100 (exclusive)"
        )
    if c.pullback_lookback_candles <= 0:
        raise ConfigError("GOLDSIGNAL_TRENDPULLBACK_PULLBACK_LOOKBACK_CANDLES must be positive")
    if c.max_extension_atr_multiple <= 0:
        raise ConfigError("GOLDSIGNAL_TRENDPULLBACK_MAX_EXTENSION_ATR_MULTIPLE must be positive")
    if not c.structure_lookbacks or any(lb <= 0 for lb in c.structure_lookbacks):
        raise ConfigError(
            "GOLDSIGNAL_TRENDPULLBACK_STRUCTURE_LOOKBACKS must be a non-empty list of positive ints"
        )
    if c.min_net_reward_r <= 0:
        raise ConfigError("GOLDSIGNAL_TRENDPULLBACK_MIN_NET_REWARD_R must be positive")
    if c.cooldown_minutes < 0:
        raise ConfigError("GOLDSIGNAL_TRENDPULLBACK_COOLDOWN_MINUTES must not be negative")
    if c.max_signals_per_session <= 0:
        raise ConfigError("GOLDSIGNAL_TRENDPULLBACK_MAX_SIGNALS_PER_SESSION must be positive")
    if c.setup_expiration_candles <= 0:
        raise ConfigError("GOLDSIGNAL_TRENDPULLBACK_SETUP_EXPIRATION_CANDLES must be positive")


# --- Pure predicates -------------------------------------------------------


def is_established_trend(
    *,
    confirm_ema_fast: float,
    confirm_ema_slow: float,
    confirm_atr: float,
    trend_strength_atr_multiple: float,
) -> SignalDirection | None:
    """Higher-timeframe trend, mirroring the frozen A+ rule's own
    already-proven approach (own threshold, not shared with it)."""
    separation = confirm_ema_fast - confirm_ema_slow
    threshold = trend_strength_atr_multiple * confirm_atr
    if separation >= threshold:
        return SignalDirection.BUY
    if -separation >= threshold:
        return SignalDirection.SELL
    return None


def find_pullback_dip_index(
    rsi_vals: list[float | None],
    *,
    direction: SignalDirection,
    current_idx: int,
    lookback_candles: int,
    pullback_rsi_trigger: float,
) -> int | None:
    """The most recent candle (strictly before `current_idx`, within
    `lookback_candles`) where RSI reached at/beyond the counter-trend
    dip threshold -- objective evidence a genuine retracement occurred.
    """
    is_buy = direction == SignalDirection.BUY
    trigger = pullback_rsi_trigger if is_buy else (100 - pullback_rsi_trigger)
    earliest = max(0, current_idx - lookback_candles)
    for i in range(current_idx - 1, earliest - 1, -1):
        value = rsi_vals[i]
        if value is None:
            continue
        if is_buy and value <= trigger:
            return i
        if not is_buy and value >= trigger:
            return i
    return None


def is_first_rsi_crossing(
    rsi_vals: list[float | None],
    *,
    direction: SignalDirection,
    dip_idx: int,
    current_idx: int,
    pullback_rsi_confirm: float,
) -> bool:
    """True if `current_idx` is the *first* candle after `dip_idx` whose
    RSI crosses back through `pullback_rsi_confirm` -- not just *a*
    candle that happens to be above it, which would let every RSI
    up-tick after an old dip re-qualify. Mirrors
    `indicators/structure.py::breakout_and_retest`'s "find an index,
    then scan forward for one qualifying event" shape.
    """
    is_buy = direction == SignalDirection.BUY
    threshold = pullback_rsi_confirm if is_buy else (100 - pullback_rsi_confirm)

    for i in range(dip_idx + 1, current_idx):
        value = rsi_vals[i]
        if value is None:
            continue
        already_crossed = value >= threshold if is_buy else value <= threshold
        if already_crossed:
            return False

    current = rsi_vals[current_idx]
    if current is None:
        return False
    return current >= threshold if is_buy else current <= threshold


def pullback_swing_extreme(
    entry_candles: list[Candle], *, direction: SignalDirection, dip_idx: int, current_idx: int
) -> float:
    """The pullback leg's own structural extreme -- min low (BUY) / max
    high (SELL) over the candles from the dip to now -- used for both
    the stop-loss reference and the extension check. Derived from
    `dip_idx` rather than a separately-tuned window, so the stop/extension
    reference is tied to the specific pullback being traded.
    """
    leg = entry_candles[dip_idx : current_idx + 1]
    if direction == SignalDirection.BUY:
        return min(c.low for c in leg)
    return max(c.high for c in leg)


def is_extended(
    *,
    direction: SignalDirection,
    current_close: float,
    current_ema_fast: float,
    atr: float,
    max_extension_atr_multiple: float,
) -> bool:
    """True if price has already run too far past the fast EMA to be a
    sane pullback entry.

    An earlier design also compared distance to the pullback's own
    swing low/high (mirroring `compute_stop_loss`'s "ATR-based vs.
    structural, take the more conservative" shape) -- empirically this
    was wrong, not just redundant: a real synthetic-data scan showed it
    rejected every single otherwise-confirmed setup (0/53), because the
    distance from the reclaim candle back to the pullback's *own low* is
    large by definition (that's what a retracement is) -- it doesn't
    measure extension at all, it measures the depth of the very
    retracement the rule requires. Removed rather than reworked with a
    second, differently-anchored structural reference, to keep this
    gate to the one thing it can objectively measure well.
    """
    is_buy = direction == SignalDirection.BUY
    max_distance = max_extension_atr_multiple * atr
    ema_distance = (
        (current_close - current_ema_fast) if is_buy else (current_ema_fast - current_close)
    )
    return ema_distance > max_distance


# --- Orchestration ----------------------------------------------------------


def _min_required_candles(mode_config: ModeConfig, family_config: TrendPullbackConfig) -> int:
    return (
        max(
            mode_config.ema_slow_period,
            mode_config.rsi_period + 1,
            mode_config.atr_period,
            family_config.pullback_lookback_candles + 1,
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
        confidence_score=confidence,
        reason=reason,
    )


def evaluate_trend_pullback(
    *,
    mode: StrategyMode,
    version: str,
    mode_config: ModeConfig,
    family_config: TrendPullbackConfig,
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

    entry_closes = [c.close for c in entry_candles]
    ema_fast_vals = compute_ema(entry_closes, mode_config.ema_fast_period)
    rsi_vals = compute_rsi(entry_closes, mode_config.rsi_period)
    atr_vals = compute_atr(entry_candles, mode_config.atr_period)

    confirm_closes = [c.close for c in confirmation_candles]
    confirm_ema_fast_vals = compute_ema(confirm_closes, mode_config.ema_fast_period)
    confirm_ema_slow_vals = compute_ema(confirm_closes, mode_config.ema_slow_period)
    confirm_atr_vals = compute_atr(confirmation_candles, mode_config.atr_period)

    current_idx = len(entry_candles) - 1
    if (
        ema_fast_vals[current_idx] is None
        or rsi_vals[current_idx] is None
        or atr_vals[current_idx] is None
        or confirm_ema_fast_vals[-1] is None
        or confirm_ema_slow_vals[-1] is None
        or confirm_atr_vals[-1] is None
    ):
        return no_trade("indicators_unavailable")

    current_atr = atr_vals[current_idx]
    current_ema_fast = ema_fast_vals[current_idx]

    direction = is_established_trend(
        confirm_ema_fast=confirm_ema_fast_vals[-1],
        confirm_ema_slow=confirm_ema_slow_vals[-1],
        confirm_atr=confirm_atr_vals[-1],
        trend_strength_atr_multiple=family_config.trend_strength_atr_multiple,
    )
    if direction is None:
        return no_trade("trend_not_established", failed=["trend_established"])
    met = ["trend_established"]
    failed: list[str] = []

    dip_idx = find_pullback_dip_index(
        rsi_vals,
        direction=direction,
        current_idx=current_idx,
        lookback_candles=family_config.pullback_lookback_candles,
        pullback_rsi_trigger=family_config.pullback_rsi_trigger,
    )
    if dip_idx is None:
        failed.append("pullback_dip_found")
        return no_trade("pullback_not_found", met=met, failed=failed)
    met.append("pullback_dip_found")

    rsi_crossed = is_first_rsi_crossing(
        rsi_vals,
        direction=direction,
        dip_idx=dip_idx,
        current_idx=current_idx,
        pullback_rsi_confirm=family_config.pullback_rsi_confirm,
    )
    (met if rsi_crossed else failed).append("rsi_first_crossing")

    current_candle = entry_candles[current_idx]
    directional = (
        current_candle.close > current_candle.open
        if direction == SignalDirection.BUY
        else current_candle.close < current_candle.open
    )
    (met if directional else failed).append("directional_close")

    reclaimed = (
        current_candle.close > current_ema_fast
        if direction == SignalDirection.BUY
        else current_candle.close < current_ema_fast
    )
    (met if reclaimed else failed).append("ema_reclaimed")

    if not (rsi_crossed and directional and reclaimed):
        return no_trade("pullback_not_confirmed", met=met, failed=failed)

    swing_extreme = pullback_swing_extreme(
        entry_candles, direction=direction, dip_idx=dip_idx, current_idx=current_idx
    )

    extended = is_extended(
        direction=direction,
        current_close=current_candle.close,
        current_ema_fast=current_ema_fast,
        atr=current_atr,
        max_extension_atr_multiple=family_config.max_extension_atr_multiple,
    )
    (failed if extended else met).append("not_extended")
    if extended:
        return no_trade("price_already_extended", met=met, failed=failed)

    entry_price = current_candle.close
    stop_loss = compute_stop_loss(
        direction=direction,
        entry_price=entry_price,
        atr=current_atr,
        atr_stop_multiplier=mode_config.atr_stop_multiplier,
        structural_ref=swing_extreme,
        tolerance=0.0,
    )
    risk = abs(entry_price - stop_loss)
    if risk <= 0:
        failed.append("sufficient_reward_after_costs")
        return no_trade("invalid_risk_distance", met=met, failed=failed)

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
        failed.append("sufficient_reward_after_costs")
        return no_trade("no_target_clears_minimum_net_reward_after_costs", met=met, failed=failed)
    met.append("sufficient_reward_after_costs")

    setup_expiration = (
        signal_timestamp + family_config.setup_expiration_candles * entry_timeframe.duration
    )
    invalidation_conditions = [
        f"price closes back {'below' if direction == SignalDirection.BUY else 'above'} "
        f"the pullback structure {swing_extreme:.2f} before entry is filled",
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
        f"{direction.value}: pullback from {swing_extreme:.2f} confirmed by RSI cross, "
        f"directional close, and EMA reclaim within an established trend"
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
        conditions_failed=failed,
        confidence_score=confidence,
        reason=reason,
    )


class TrendPullbackStrategy:
    """`Strategy`-protocol wrapper, mirroring `ScalpStrategy`'s shape
    exactly so anything structurally typed against `Strategy` (backtest
    engine, candidate-walk harness) keeps working unmodified.
    """

    mode = StrategyMode.TREND_PULLBACK
    version = STRATEGY_VERSION

    def __init__(
        self, mode_config: ModeConfig, family_config: TrendPullbackConfig, instrument: str
    ):
        self.config = mode_config  # satisfies Strategy Protocol's `config: ModeConfig`
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
        return evaluate_trend_pullback(
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
