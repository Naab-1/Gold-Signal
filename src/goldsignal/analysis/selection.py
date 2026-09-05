"""Selection requirements (STRATEGY RESEARCH AND REPLACEMENT program,
Phase 8) -- see docs/phase8_selection_requirements.md for the full spec
and its result applied to Phase 7's real cross-family evaluation.

Four criteria, chosen and written down before being applied to any
result, not reverse-engineered from whichever candidate looked best.
Each guards against a specific failure mode already seen in this
program's own real-data findings:

- `min_development_trades` / `min_validation_trades`: a candidate can't
  pass on the strength of a handful of trades. Directly motivated by
  Phase 7's Breakout and Retest result (80% win rate, +1.18R
  expectancy, on 5 development trades and ZERO validation trades --
  unusable regardless of how good the raw number looks).
- `min_development_expectancy_r`: the larger, older split must show a
  real edge, not just be non-negative.
- `min_validation_expectancy_r`: the edge must show up AGAIN,
  independently, in the untouched validation split -- not merely
  "not much worse than development." Directly motivated by Phase 7's
  Trend Pullback result flipping sign between its own development
  (+0.15R) and validation (-0.53R) splits, and by the Phase 6 vs.
  Phase 7 instability finding for the same family across two different
  real-data windows.

A candidate that fails any criterion fails selection outright -- this
is a gate, not a weighted score with penalties (unlike Phase 6's
optimization framework, which scores and ranks; this phase decides
pass/fail). Every failure reason is recorded, not just whichever
criterion happened to fail first, so a candidate that's simply too new
(too few trades) isn't reported the same way as one that's actively
losing money.

Selection here operates ONLY on development and validation data --
`analysis/performance_evaluation.py::CandidateEvaluation`, this
module's input, never carries final-out-of-sample data in the first
place. A candidate that passes this gate is eligible for a final-oos
evaluation (via `backtest/final_oos_ledger.py`'s guard); this module
itself never touches or unlocks that step -- it only decides
eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass

from goldsignal.analysis.performance_evaluation import CandidateEvaluation


@dataclass(frozen=True)
class SelectionCriteria:
    min_development_trades: int = 30
    min_validation_trades: int = 15
    min_development_expectancy_r: float = 0.0
    min_validation_expectancy_r: float = 0.0


@dataclass(frozen=True)
class SelectionResult:
    family: str
    instrument: str
    passed: bool
    failures: list[str]
    development_trades: int
    development_expectancy_r: float
    validation_trades: int
    validation_expectancy_r: float


def evaluate_selection(
    evaluation: CandidateEvaluation, criteria: SelectionCriteria
) -> SelectionResult:
    failures: list[str] = []
    dev = evaluation.development
    val = evaluation.validation

    if dev.total_trades < criteria.min_development_trades:
        failures.append(
            f"development trades ({dev.total_trades}) below minimum "
            f"({criteria.min_development_trades})"
        )
    if val.total_trades < criteria.min_validation_trades:
        failures.append(
            f"validation trades ({val.total_trades}) below minimum "
            f"({criteria.min_validation_trades})"
        )
    if dev.expectancy_r <= criteria.min_development_expectancy_r:
        failures.append(
            f"development expectancy ({dev.expectancy_r:.4f}R) not above minimum "
            f"({criteria.min_development_expectancy_r}R)"
        )
    if val.expectancy_r <= criteria.min_validation_expectancy_r:
        failures.append(
            f"validation expectancy ({val.expectancy_r:.4f}R) not above minimum "
            f"({criteria.min_validation_expectancy_r}R)"
        )

    return SelectionResult(
        family=evaluation.family,
        instrument=evaluation.instrument,
        passed=not failures,
        failures=failures,
        development_trades=dev.total_trades,
        development_expectancy_r=dev.expectancy_r,
        validation_trades=val.total_trades,
        validation_expectancy_r=val.expectancy_r,
    )


def evaluate_selection_batch(
    evaluations: list[CandidateEvaluation], criteria: SelectionCriteria
) -> list[SelectionResult]:
    return [evaluate_selection(e, criteria) for e in evaluations]
