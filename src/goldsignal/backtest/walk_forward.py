"""Walk-forward fold generation for the STRATEGY RESEARCH AND REPLACEMENT
program's Phase 3 (chronological data separation): "train on an earlier
window, validate on the next window, move both windows forward, aggregate
genuinely out-of-sample results."

This module only generates windows — it never runs a strategy. No
candidate strategy exists yet (Phase 4 hasn't started); Phase 4's
evaluation will consume a `WalkForwardFold`'s `validate_candles` the same
way `analysis/tier_comparison.py`'s `_walk` already consumes a bounded
candle window, reusing that pattern rather than inventing a fourth walk
implementation.

A meaningful multi-fold walk-forward is only currently defensible for
XAU/USD (2 years, ~173K 5-minute candles, confirmed fetchable this
session). EUR/USD, GBP/USD, and USD/JPY are confirmed only to 180 days
(~52K candles each) — enough for the existing two-way split, not enough
for walk-forward to mean anything beyond 1-2 folds. This module is
generic and instrument-agnostic; it is deliberately not run against real
forex data until a deeper history pull is attempted for those three (see
docs/phase3_data_separation.md).
"""

from __future__ import annotations

from dataclasses import dataclass

from goldsignal.backtest.models import BacktestTrade
from goldsignal.models.candle import Candle


@dataclass(frozen=True)
class WalkForwardFold:
    train_candles: list[Candle]
    validate_candles: list[Candle]


def generate_walk_forward_folds(
    candles: list[Candle],
    *,
    n_folds: int,
    min_train_candles: int,
) -> list[WalkForwardFold]:
    """Anchored (expanding) walk-forward folds: each fold's train window is
    a strict superset of the previous fold's (`candles[0:train_end]`),
    validate windows are disjoint and chronologically forward-only
    (`candles[train_end:validate_end]`), and the last fold absorbs any
    remainder from integer division so no trailing candles are silently
    dropped.

    An expanding window (rather than a fixed-size rolling one) needs no
    extra window-size parameter and preserves maximum training data per
    fold given today's thin forex depth — consistent with how
    `split.py`/`live/catchup.py` already treat history as a strictly-
    growing prefix, never a sliding subset.

    Raises `ValueError` (never a silently-shorter fold list) if there
    isn't enough data to give every fold at least one validate candle.
    """
    if n_folds <= 0:
        raise ValueError("n_folds must be positive")
    if min_train_candles <= 0:
        raise ValueError("min_train_candles must be positive")
    if len(candles) < min_train_candles + n_folds:
        raise ValueError(
            f"not enough candles ({len(candles)}) for {n_folds} fold(s) with "
            f"min_train_candles={min_train_candles} -- need at least "
            f"{min_train_candles + n_folds}"
        )

    remaining = len(candles) - min_train_candles
    validate_size = remaining // n_folds

    folds: list[WalkForwardFold] = []
    train_end = min_train_candles
    for fold_idx in range(n_folds):
        is_last = fold_idx == n_folds - 1
        validate_end = len(candles) if is_last else train_end + validate_size
        folds.append(
            WalkForwardFold(
                train_candles=candles[:train_end],
                validate_candles=candles[train_end:validate_end],
            )
        )
        train_end = validate_end

    return folds


def aggregate_fold_trades(fold_trades: list[list[BacktestTrade]]) -> list[BacktestTrade]:
    """Concatenate each fold's validate-window trades into one pooled,
    genuinely-out-of-sample result. A one-line helper, kept here (not
    left to each caller) so Phase 4 code doesn't reinvent it per strategy.
    """
    aggregated: list[BacktestTrade] = []
    for trades in fold_trades:
        aggregated.extend(trades)
    return aggregated
