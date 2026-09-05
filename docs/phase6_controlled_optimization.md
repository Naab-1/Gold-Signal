# Phase 6: Controlled Optimization

**Status: framework implemented and verified against synthetic data.
Not yet applied to real history for any candidate family** — consistent
with every Phase 4/5 deliverable so far: this document specifies the
optimization framework and proves its mechanics are correct, not a set
of tuned, evidence-backed parameter choices.

## What "controlled" means here

Per the project's own standing bar for this phase: **bounded ranges,
record every configuration tested, penalize complexity, never optimize
on final-out-of-sample data.** `analysis/optimization.py` enforces all
four structurally, not as discipline a future run could accidentally
skip:

1. **Bounded ranges.** `run_controlled_optimization`'s `param_grid`
   names only the specific fields being searched, each with an
   explicit, finite list of candidate values. There is no free-form or
   unbounded search — fields left out of the grid stay fixed at
   `baseline_params`.
2. **Every configuration tested is recorded.** `OptimizationResult.trials`
   holds one `OptimizationTrial` per grid combination *plus* the
   baseline itself, each carrying its own development *and* validation
   summary — a full audit trail survives even for rejected
   configurations. `write_trials_log` persists the entire result as
   JSON.
3. **Complexity is penalized.** A trial's score is its development-split
   expectancy minus `complexity_penalty_per_param` for every field it
   changes away from the baseline. A configuration only wins by
   improving the development result by more than the cost of the new
   degrees of freedom it introduces — not by merely edging out the
   baseline on a single metric.
4. **Never optimized on validation or final-out-of-sample data.**
   Selection is decided purely from each trial's DEVELOPMENT summary.
   The validation summary is carried on every trial for a human to read
   afterward as an honest, untouched check of whether the winning
   configuration's edge looks real or like search noise — it plays no
   part in the selection arithmetic. Final-out-of-sample data is never
   touched at all: `analysis/candidate_walk.py::run_candidate_dev_validation`
   (reused here completely unmodified) structurally only ever returns
   development and validation summaries, the same guardrail every Phase
   4 family's own real-data sanity check already relies on.

An additional guard beyond the four above: any trial whose development
split produces fewer than `min_dev_trades` trades is disqualified from
selection (though still recorded) — a configuration can't be judged
better on the strength of two lucky trades. And a winning configuration
must clear the penalty *and* a separate `min_improvement_r` margin over
the baseline, so a razor-thin, likely-noise improvement doesn't win by
default.

## Why it's generic across every Phase 4 family

`run_controlled_optimization` never imports or knows about any specific
family's config dataclass. The caller supplies two small factories:

- `build_family_config(params: dict) -> FamilyConfig` — constructs that
  family's own frozen config dataclass directly from a resolved
  parameter dict (e.g. `lambda p: TrendPullbackConfig(**p)`).
- `build_strategy(family_config) -> Strategy` — wraps it in that
  family's `Strategy`-protocol class (e.g.
  `lambda fc: TrendPullbackStrategy(mode_config, fc, instrument)`).

This means the same optimization module works unmodified for all five
Phase 4 candidates (and any future family) — exactly the same "generic
harness, family supplies the specifics" shape `analysis/candidate_walk.py`
already established for walking a strategy forward.

## Verification performed

- **Selection-arithmetic tests** (`tests/test_optimization.py`), with
  `run_candidate_dev_validation` monkeypatched to a fully controlled
  fake so the tests isolate the optimization/selection logic itself
  from any real strategy or candle data:
  - baseline selected when no grid configuration improves on it;
  - a configuration selected only when its improvement clears both the
    complexity penalty *and* `min_improvement_r`;
  - a configuration disqualified (not merely scored low) when its
    development trade count falls below `min_dev_trades`, even when its
    raw expectancy looks excellent;
  - the baseline itself is selected with an explanatory reason when even
    the baseline's own trade count is too low to judge anything
    meaningfully;
  - a grid value that happens to equal the baseline is never evaluated
    twice;
  - `write_trials_log` produces valid JSON carrying every trial.
- **One end-to-end test** wires a real Phase 4 candidate (Trend
  Pullback) through the framework against synthetic
  `MockDataProvider` data, proving the factory-based interface actually
  works with a real `Strategy` and produces development/validation
  summaries on every trial — not asserting that any improvement is
  found (synthetic random-walk data has no genuine edge for a search to
  discover; that would be tuning to noise, not evidence).
- Full project test suite (452 tests) and `ruff check`/`ruff format --check` pass.
- Zero lines changed in any existing file — `analysis/optimization.py` and `tests/test_optimization.py` are both new; every Phase 4 candidate family and the frozen A+/A-tier baseline are completely untouched.

## Why this phase deliberately stops short of a real-history run

Unlike Phase 4/5's synthetic-first validation (where synthetic data with
a known, engineered ground truth is *more* rigorous than real data for
proving a classifier or strategy's logic is correct), a parameter
search is only meaningful against real market data — searching a
stationary random walk for a "better" parameter would be tuning to
noise and reporting it as if it were evidence. Running this framework
for real requires pulling a family's development-slice real history
(one `get_candles` call per instrument/timeframe pair, reused across
every grid combination — the fetch cost doesn't scale with grid size),
which spends TwelveData API quota. Given this project's own prior
production incident from quota exhaustion (`docs/session_checkpoint_2026-09-02.md`
and this session's earlier rate-limit fix), that pull is deliberately
left as an explicit, separate next step rather than spent automatically
in this phase.

## Suggested next step (not yet performed)

Run `run_controlled_optimization` for one candidate family (Trend
Pullback is the natural first choice — it has the most real-data
history already available in this program, on XAU/USD) against a
modest real development-slice pull (the same ~90-day scale referenced
throughout Phase 4's own "sanity check" convention), with a small grid
over 1-2 of its most impactful fields (e.g.
`max_extension_atr_multiple`, `trend_strength_atr_multiple`). Report
whichever configuration is selected — including the honest possibility
that the baseline wins outright, which would itself be a legitimate,
informative result given how thin every real edge in this program has
been so far.

## Explicitly NOT done in this phase

No real-history optimization run for any family. No comparison across
candidate families (Phase 7's job). No selection-requirements gate
applied (Phase 8). No live-alert activation — the standing instruction
to present evidence only, and never deploy without explicit approval,
is unaffected by this phase existing.
