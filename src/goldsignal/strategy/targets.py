"""Profit-target (TP1/TP2/TP3) selection.

Targets are never mechanically invented (e.g. "always 1R/2R/3R"). Candidate
levels come from real market structure (recent swing highs/lows at several
lookback windows); a candidate only becomes a target if its *net-of-cost*
reward clears the configured minimum and meaningfully exceeds the previous
target's net reward. If not even one candidate clears the bar, no targets
are returned and the caller must produce NO_TRADE.
"""

from __future__ import annotations

from collections.abc import Sequence

from goldsignal.indicators.structure import recent_swing_levels
from goldsignal.models.candle import Candle
from goldsignal.models.signal import ProfitTarget, SignalDirection
from goldsignal.strategy.cost_model import CostEstimate, gross_reward_r, net_reward_r

_TARGET_LABELS = ("TP1", "TP2", "TP3")


def candidate_structure_levels(
    candles: Sequence[Candle],
    *,
    direction: SignalDirection,
    lookbacks: Sequence[int],
) -> list[float]:
    """Distinct resistance levels (BUY) or support levels (SELL) found by
    scanning swing highs/lows over each lookback window in `lookbacks`.
    """
    if direction not in (SignalDirection.BUY, SignalDirection.SELL):
        raise ValueError("direction must be BUY or SELL")

    levels: set[float] = set()
    for lookback in lookbacks:
        resistance, support = recent_swing_levels(candles, lookback)
        level = resistance if direction == SignalDirection.BUY else support
        if level is not None:
            levels.add(level)
    return sorted(levels)


def build_targets(
    *,
    direction: SignalDirection,
    entry: float,
    stop_loss: float,
    candidate_levels: Sequence[float],
    costs: CostEstimate,
    min_net_reward_r: float,
    allow_tp3: bool,
) -> list[ProfitTarget]:
    """Select up to three targets from `candidate_levels` (already computed
    for the correct direction, e.g. via `candidate_structure_levels`).

    A candidate becomes TPn only if:
    - it sits beyond entry on the correct side,
    - its net-of-cost reward is >= min_net_reward_r, and
    - its net-of-cost reward is strictly greater than the previous
      accepted target's (so targets are meaningfully spaced, not
      clustered).

    TP3 is only ever added when `allow_tp3` is True (the caller decides
    this from trend-strength/structure, e.g. EMA separation vs ATR).
    """
    if direction not in (SignalDirection.BUY, SignalDirection.SELL):
        raise ValueError("direction must be BUY or SELL")

    if direction == SignalDirection.BUY:
        ordered = sorted(lvl for lvl in candidate_levels if lvl > entry)
    else:
        ordered = sorted((lvl for lvl in candidate_levels if lvl < entry), reverse=True)

    targets: list[ProfitTarget] = []
    prev_net_r = 0.0
    max_targets = 3 if allow_tp3 else 2

    for level in ordered:
        if len(targets) >= max_targets:
            break
        net_r = net_reward_r(entry=entry, stop_loss=stop_loss, target_price=level, costs=costs)
        if net_r < min_net_reward_r or net_r <= prev_net_r:
            continue
        label = _TARGET_LABELS[len(targets)]
        gross_r = gross_reward_r(entry=entry, stop_loss=stop_loss, target_price=level)
        targets.append(ProfitTarget(label=label, price=level, r_multiple=gross_r))
        prev_net_r = net_r

    return targets
