"""Controlled parameter optimization (STRATEGY RESEARCH AND REPLACEMENT
program, Phase 6) -- see docs/phase6_controlled_optimization.md for the
full spec and a worked example against real history.

"Controlled" means four things, all enforced structurally by this
module rather than left to discipline:

1. **Bounded ranges.** The caller supplies a `param_grid` naming only the
   specific fields being searched and an explicit, finite list of values
   for each -- there is no free-form or unbounded search here. Fields
   left out of the grid stay fixed at `baseline_params`.
2. **Every configuration tested is recorded**, not just the winner --
   `OptimizationResult.trials` holds one `OptimizationTrial` per grid
   combination (plus the baseline itself), each carrying its own
   development AND validation summary, so a full audit trail exists
   even for configurations that were rejected.
3. **Complexity is penalized.** A configuration's score is its
   development-split expectancy minus `complexity_penalty_per_param`
   for every field it changes away from `baseline_params` -- so a
   configuration only wins by improving the development result by more
   than the number of new degrees of freedom it costs, not by merely
   edging out the baseline on a single metric.
4. **Never optimized on the validation or final-out-of-sample split.**
   Selection is decided purely from each trial's DEVELOPMENT summary.
   The validation summary is carried on every trial for a human to read
   afterward as an honest, untouched check of whether the winning
   configuration's edge was real or search noise -- it plays no part in
   the selection arithmetic itself. Final-out-of-sample data is never
   touched by this module at all; `analysis/candidate_walk.py`'s own
   `run_candidate_dev_validation` (reused here unmodified) structurally
   only ever returns development and validation summaries.

This module is generic across every Phase 4 candidate family: the
caller supplies small factory functions (`build_family_config`,
`build_strategy`) rather than this module knowing about any specific
family's config dataclass.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from goldsignal.analysis.candidate_walk import run_candidate_dev_validation
from goldsignal.backtest.export import to_jsonable
from goldsignal.backtest.models import BacktestSummary
from goldsignal.models.candle import Candle
from goldsignal.models.signal import StrategyMode
from goldsignal.strategy.base import Strategy
from goldsignal.strategy.trade_management import TradeManagementPreset


@dataclass(frozen=True)
class OptimizationTrial:
    params: dict[str, Any]
    num_changed_params: int
    development: BacktestSummary
    validation: BacktestSummary
    penalized_score: float | None
    disqualified_reason: str | None = None


@dataclass(frozen=True)
class OptimizationResult:
    trials: list[OptimizationTrial]
    baseline_trial: OptimizationTrial
    selected_trial: OptimizationTrial
    selected_is_baseline: bool
    selection_reason: str


def _count_changed_params(params: Mapping[str, Any], baseline_params: Mapping[str, Any]) -> int:
    return sum(1 for key, value in params.items() if baseline_params.get(key) != value)


def _build_trial(
    *,
    params: dict[str, Any],
    baseline_params: Mapping[str, Any],
    build_family_config: Callable[[Mapping[str, Any]], Any],
    build_strategy: Callable[[Any], Strategy],
    mode: StrategyMode,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    dev_ratio: float,
    validation_ratio: float,
    preset: TradeManagementPreset,
    complexity_penalty_per_param: float,
    min_dev_trades: int,
) -> OptimizationTrial:
    family_config = build_family_config(params)
    strategy = build_strategy(family_config)
    summary = run_candidate_dev_validation(
        strategy,
        mode,
        entry_candles,
        confirmation_candles,
        preset=preset,
        dev_ratio=dev_ratio,
        validation_ratio=validation_ratio,
    )
    num_changed = _count_changed_params(params, baseline_params)

    if summary.development.total_trades < min_dev_trades:
        return OptimizationTrial(
            params=params,
            num_changed_params=num_changed,
            development=summary.development,
            validation=summary.validation,
            penalized_score=None,
            disqualified_reason=(
                f"development trades ({summary.development.total_trades}) below "
                f"min_dev_trades ({min_dev_trades}) -- too few to score meaningfully"
            ),
        )

    penalized_score = summary.development.expectancy_r - complexity_penalty_per_param * num_changed
    return OptimizationTrial(
        params=params,
        num_changed_params=num_changed,
        development=summary.development,
        validation=summary.validation,
        penalized_score=penalized_score,
    )


def run_controlled_optimization(
    *,
    build_family_config: Callable[[Mapping[str, Any]], Any],
    build_strategy: Callable[[Any], Strategy],
    baseline_params: Mapping[str, Any],
    param_grid: Mapping[str, Sequence[Any]],
    mode: StrategyMode,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    dev_ratio: float = 0.7,
    validation_ratio: float = 0.15,
    preset: TradeManagementPreset = TradeManagementPreset.BALANCED,
    complexity_penalty_per_param: float = 0.02,
    min_improvement_r: float = 0.02,
    min_dev_trades: int = 20,
) -> OptimizationResult:
    """Runs the baseline configuration plus every combination in
    `param_grid` (a small, explicit dict of field name -> candidate
    values) against `entry_candles`/`confirmation_candles`'s development
    split only, and selects whichever configuration has the highest
    complexity-penalized development expectancy -- but only if it beats
    the unmodified baseline by at least `min_improvement_r`; otherwise
    the baseline itself is selected. `entry_candles`/`confirmation_candles`
    should be the FULL history a caller intends to search over -- the
    dev/validation split is applied internally per trial via
    `run_candidate_dev_validation`, exactly the same split every trial
    shares, so trials remain directly comparable.
    """
    trial_kwargs = dict(
        baseline_params=baseline_params,
        build_family_config=build_family_config,
        build_strategy=build_strategy,
        mode=mode,
        entry_candles=entry_candles,
        confirmation_candles=confirmation_candles,
        dev_ratio=dev_ratio,
        validation_ratio=validation_ratio,
        preset=preset,
        complexity_penalty_per_param=complexity_penalty_per_param,
        min_dev_trades=min_dev_trades,
    )

    baseline_trial = _build_trial(params=dict(baseline_params), **trial_kwargs)
    trials = [baseline_trial]

    grid_keys = list(param_grid.keys())
    for combo in itertools.product(*(param_grid[k] for k in grid_keys)):
        params = dict(baseline_params)
        params.update(dict(zip(grid_keys, combo, strict=True)))
        if params == dict(baseline_params):
            continue  # already evaluated as the baseline trial above
        trials.append(_build_trial(params=params, **trial_kwargs))

    if baseline_trial.penalized_score is None:
        return OptimizationResult(
            trials=trials,
            baseline_trial=baseline_trial,
            selected_trial=baseline_trial,
            selected_is_baseline=True,
            selection_reason=(
                "baseline configuration's own development trade count is too low to "
                "evaluate any optimization meaningfully -- keeping the baseline "
                "unchanged rather than selecting an alternative with no reliable "
                "point of comparison"
            ),
        )

    qualified = [t for t in trials if t.penalized_score is not None]
    best = max(qualified, key=lambda t: t.penalized_score)

    if (
        best is baseline_trial
        or best.penalized_score <= baseline_trial.penalized_score + min_improvement_r
    ):
        return OptimizationResult(
            trials=trials,
            baseline_trial=baseline_trial,
            selected_trial=baseline_trial,
            selected_is_baseline=True,
            selection_reason=(
                "no tested configuration improved the complexity-penalized "
                f"development expectancy over the baseline by at least "
                f"min_improvement_r ({min_improvement_r}) -- keeping the baseline"
            ),
        )

    return OptimizationResult(
        trials=trials,
        baseline_trial=baseline_trial,
        selected_trial=best,
        selected_is_baseline=False,
        selection_reason=(
            f"selected configuration improved complexity-penalized development "
            f"expectancy from {baseline_trial.penalized_score:.4f}R to "
            f"{best.penalized_score:.4f}R ({best.num_changed_params} parameter(s) "
            f"changed from baseline)"
        ),
    )


def write_trials_log(result: OptimizationResult, path: str | Path) -> None:
    """Persists every trial (tested params, dev/validation summaries,
    penalized score, disqualification reason if any) as JSON -- the
    durable audit trail behind "every configuration tested is recorded,"
    not just whichever one was ultimately selected.
    """
    payload = {
        "baseline_trial": to_jsonable(result.baseline_trial),
        "selected_trial": to_jsonable(result.selected_trial),
        "selected_is_baseline": result.selected_is_baseline,
        "selection_reason": result.selection_reason,
        "trials": [to_jsonable(t) for t in result.trials],
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
