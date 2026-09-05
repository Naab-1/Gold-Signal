# Phase 7: Performance Evaluation

**Status: framework implemented, unit-tested against synthetic data,
and applied once against real history across all five Phase 4
candidates on XAU/USD.** As with every real-data finding in this
program, the result below is reported honestly and is **not a
verdict** on any candidate.

## What this phase does

Two things earlier phases explicitly deferred to here:

1. **Regime correlation.** Phase 5 built a diagnostic 5-way market
   regime classifier "for diagnostic use... not [Phase 5's] own job."
   This phase is that job: every trade a candidate produces is tagged
   with whichever regime the market was in at that trade's signal
   timestamp (using only candles at or before that timestamp, so the
   tag never looks ahead), letting a candidate's development/validation
   performance be broken down by regime instead of reported as one
   blended number.
2. **Cross-family comparison.** Phase 4 built five independent
   candidates one at a time and never blended their statistics. This
   phase runs each candidate's own walk and reports them side by side
   on development and validation, still never blended into a combined
   metric and never touching final-out-of-sample data.

`analysis/performance_evaluation.py` is the shared module:

- `regime_at_or_before(timestamp, regime_candles, regime_series)`, a
  lookahead-safe join between a trade's signal timestamp and a
  separately-classified regime series (typically a shared, higher
  timeframe reused across every candidate being evaluated, so tags are
  comparable across families rather than each reading its own entry
  timeframe's noise differently).
- `tag_trades_with_regime` / `group_trades_by_session`, partitioning a
  trade list into regime or session buckets (session grouping reuses
  `notifications/sessions.py::session_label`, the same key
  `analysis/tier_comparison.py` already uses for its own per-session
  counts).
- `summarize_groups`, which calls the existing, unmodified
  `backtest/metrics.py::compute_summary` per bucket.
- `evaluate_candidate_performance`, which walks a `Strategy` once (via
  `analysis/candidate_walk.py::walk_candidate`, reused unmodified),
  splits development/validation/final-out-of-sample (the final-oos
  slice is computed then immediately discarded, never inspected or
  returned, the same guardrail Phase 6's optimization framework already
  enforces), and returns overall plus regime- and session-broken-down
  summaries for development and validation only.

## A real bug found and fixed while producing this phase's results

`backtest/export.py::to_jsonable` (shared, also used by
`backtest/final_oos_ledger.py` and Phase 6's `write_trials_log`) only
recursed into dataclasses, Enums, datetimes, and lists, not plain
dicts. `CandidateEvaluation`'s regime/session breakdowns are
`dict[str, BacktestSummary]` fields, so writing this phase's real
results to JSON crashed with `TypeError: Object of type BacktestSummary
is not JSON serializable`. Fixed by adding a dict branch to
`to_jsonable` (recursing into each value, same as the existing list
branch); two regression tests added
(`tests/test_backtest_export.py::test_to_jsonable_recurses_into_dict_values`
and `test_to_jsonable_handles_nested_dict_inside_a_dataclass_field`).
This is a small, purely additive fix (previously-unsupported input that
raised now works; nothing that worked before changed) to a file every
prior phase's JSON export already depended on.

## Verification performed (synthetic data)

- 8 unit tests (`tests/test_performance_evaluation.py`): the
  lookahead-safe regime join (before-first-candle, exactly-at, between,
  after-last, and an unclassifiable-series case), regime tagging groups
  trades correctly (including an `UNKNOWN` bucket for trades with no
  classifiable regime), `summarize_groups` matches calling
  `compute_summary` directly, session grouping partitions every trade
  exactly once, and an end-to-end run with a real Phase 4 candidate
  (Trend Pullback) against synthetic `MockDataProvider` data proving
  the regime/session buckets always sum back to exactly the
  development/validation trade counts: no trade counted twice, none
  silently dropped.
- 2 new regression tests for the `to_jsonable` fix above.
- Full project test suite (462 tests) and `ruff check`/`ruff format --check` pass.
- Every Phase 4 candidate family, Phase 5's classifier, and Phase 6's
  optimization framework are completely untouched by this phase; the
  only existing file with a code change is `backtest/export.py` (the
  bug fix above, additive only).

## Real-history run: all five candidates, XAU/USD

**Data**: XAU/USD, 180 days ending 2026-09-05, fetched once per
timeframe and reused across every family that needs it: 51,825 M5
candles, 17,276 M15 candles, 4,319 H1 candles. Each family ran with its
own real, unmodified default configuration (no optimization applied in
this phase). Regime tagging used the shared M15 series for every
family, so regime labels are directly comparable across all five.
TwelveData cost: about 25 requests, comfortably inside the free-tier
daily quota.

| Family | Dev trades | Dev expectancy | Dev win rate | Dev profit factor | Val trades | Val expectancy | Val win rate |
|---|---|---|---|---|---|---|---|
| Trend Pullback | 22 | +0.1485R | 27.3% | 1.20 | 7 | -0.5299R | 14.3% |
| Breakout Continuation | 24 | -0.3774R | 20.8% | 0.53 | 2 | -1.0355R | 0.0% |
| Breakout and Retest | 5 | +1.1766R | 80.0% | 6.70 | 0 | n/a | n/a |
| Range Rejection | 114 | -0.2924R | 21.9% | 0.63 | 29 | -0.5144R | 17.2% |
| Liquidity Sweep Reversal | 358 | -0.0515R | 23.7% | 0.94 | 77 | -0.0173R | 27.3% |

Full per-family, per-regime, and per-session breakdown is in
`docs/phase7_cross_family_xauusd_results.json`.

### Why none of this should be read as a ranking

- **Breakout and Retest's headline number (80% win rate, +1.18R
  expectancy, profit factor 6.70) is 5 development trades and ZERO
  validation trades.** There is no out-of-sample check possible at all
  for this family over this window. This is close to the textbook
  shape of a small sample that looks spectacular and means nothing;
  it is reported here for completeness, not as a finding.
- **Every family with a usable validation sample showed validation
  performance flat-to-worse than development**, the ordinary,
  expected direction (Trend Pullback: +0.15R dev versus -0.53R val;
  Range Rejection: -0.29R dev versus -0.51R val, both negative;
  Liquidity Sweep Reversal: -0.05R dev versus -0.02R val, both roughly
  flat). None of the five candidates shows a credible, sample-backed
  positive edge that survives its own validation split.
- **A striking, important contrast with Phase 6's own real-history
  run**: Phase 6 evaluated Trend Pullback on a *different* 1-year
  XAU/USD window (ending earlier) and found development expectancy
  around -0.08R (baseline) to +0.06R (its selected configuration), with
  validation expectancy around +0.42R to +0.43R. This phase's 180-day
  window (ending later, real default configuration) found the
  *opposite* shape for the same family: development +0.15R, validation
  -0.53R. Two different real-data windows for the same family,
  instrument, and (essentially) configuration produced meaningfully
  different, even opposite-signed, results. That instability is itself
  the most important finding of this phase: any single real-data run
  in this program, including this one, should be read as one noisy
  sample, not a settled answer.
- **Regime and session buckets subdivide already-thin samples into
  even thinner ones.** Most buckets across all five families hold 1-9
  trades; only Range Rejection (RANGING: 35, TRENDING: 30) and
  Liquidity Sweep Reversal (TRENDING: 95, HIGH_VOLATILITY: 90,
  RANGING: 89, UNCERTAIN: 76) have regime buckets large enough that a
  longer real-data run could eventually say something meaningful about
  regime dependence. Nothing here does yet.
- **No candidate is declared better than another.** That decision, if
  it is ever made, belongs to Phase 8's selection-requirements gate,
  applied to more and better data than one 180-day window can provide.

**No configuration or candidate from this run has been activated.**
`actionable_alerts_enabled` remains `False` project-wide, per Phase 1's
standing default and the user's own instruction not to deploy without
explicit approval.

## Explicitly NOT done in this phase

No selection decision (Phase 8's job). No controlled optimization
applied here (Phase 6's own job, and only run for Trend Pullback so
far). No comparison across instruments other than XAU/USD. No
live-alert activation; the standing instruction to present evidence
only, and never deploy without explicit approval, is unaffected by
this phase's results.
