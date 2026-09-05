# Phase 6: Controlled Optimization

**Status: framework implemented, verified against synthetic data, and
now run once against real history** (Trend Pullback, XAU/USD, ~1 year
of M15/H1 data). The real run's result is reported in full below —
**it is not a verdict**. Trade counts per split are small (29–67
development, 7–13 validation), exactly the kind of sample this whole
program has repeatedly flagged as too thin to trust on its own.

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

## Real-history run: Trend Pullback, XAU/USD

Run via a one-off script (not part of the package, matching the
project's existing dev-script convention), reusing
`run_controlled_optimization` exactly as designed — no code changes
were made to support this run. TwelveData API cost: ~16 requests
(paginated M15/H1 fetch plus the default consistency spot-checks),
well inside the free-tier daily quota (52/800 used beforehand).

**Data**: XAU/USD, ~365 days ending 2026-09-05, 32,970 M15 entry
candles / 8,250 H1 confirmation candles, split 70/15/15 into
development/validation/final-out-of-sample internally by
`run_candidate_dev_validation` (final-oos untouched, per the framework's
own design).

**Grid**: `trend_strength_atr_multiple` ∈ {0.75, 1.0 (baseline), 1.25}
× `max_extension_atr_multiple` ∈ {1.0 (baseline), 1.5 (baseline), 2.0}
— 2 fields, bounded to their immediate neighbors either side of the
existing default, 5 trials total (baseline + 4 combinations).

| Changed from baseline | Dev trades | Dev expectancy | Val trades | Val expectancy | Penalized score |
|---|---|---|---|---|---|
| *(baseline)* | 46 | −0.0792R | 9 | +0.4218R | −0.0792 |
| trend=0.75, ext=1.0 | 64 | +0.0613R | 13 | +0.4301R | **+0.0213** ← selected |
| trend=1.25, ext=1.0 | 29 | −0.0845R | 7 | +0.8366R | −0.1245 |
| trend=0.75, ext=2.0 | 67 | +0.0135R | 13 | +0.4301R | −0.0265 |
| trend=1.25, ext=2.0 | 30 | −0.1154R | 7 | +0.8366R | −0.1554 |

The framework selected `trend_strength_atr_multiple=0.75`,
`max_extension_atr_multiple=1.0` over the baseline: its development
expectancy (+0.0613R) beats the baseline's (−0.0792R) by enough to
clear both the complexity penalty (2 changed parameters × 0.02 = 0.04)
and the default `min_improvement_r` margin (0.02). Full per-trial
detail (every field, not just the two searched) is in
`docs/phase6_trend_pullback_xauusd_trials.json`.

### Why this is evidence of the framework working, not evidence the rule works

- **46-67 development trades and 7-13 validation trades are small
  samples.** The project's own earlier real backtests (`docs/baseline_rejection.md`)
  used 2-year windows specifically because shorter windows didn't
  produce trade counts anyone could draw a conclusion from; this run
  used roughly half that history.
- **The winning margin is thin by construction.** +0.0613R raw
  development expectancy over 64 trades is close to what could
  plausibly be noise; the complexity penalty (0.04) very nearly
  swallows it entirely, which is exactly the "controlled" framework
  doing its job — not manufacturing false confidence, but it also means
  this is a marginal result, not a strong one.
- **Every configuration's validation expectancy is well above its own
  development expectancy** (e.g. the selected configuration: +0.06R dev
  vs. +0.43R val) — the opposite of the overfitting pattern this
  framework mainly guards against (a dev-fit config collapsing on
  validation), but with samples this small (9-13 validation trades) it
  is at least as likely to reflect a handful of favorable trades in a
  short recent window as a genuine, persistent edge. It is not treated
  here as confirmation of anything.
- **This is the first real-history run for any Phase 4 candidate in
  this entire program.** One instrument, one family, one grid. It does
  not generalize to XAU/USD's other candidates, to the other three
  instruments, or establish that Trend Pullback has a real edge —
  exactly the same caution every prior phase in this program has
  applied to its own real-data findings.

**No configuration from this run has been activated.** `actionable_alerts_enabled`
remains `False` project-wide, per Phase 1's standing default and the
user's own instruction not to deploy without explicit approval.

## Explicitly NOT done in this phase

Real-history optimization run for only one family/instrument/grid — the
other four candidates and three instruments remain unoptimized. No
comparison across candidate families (Phase 7's job). No
selection-requirements gate applied (Phase 8). No live-alert
activation — the standing instruction to present evidence only, and
never deploy without explicit approval, is unaffected by this phase's
results.
