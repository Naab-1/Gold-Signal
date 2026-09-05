# Phase 8: Selection Requirements

**Status: gate implemented, unit-tested, and applied to Phase 7's real
cross-family evaluation. Result: none of the five candidates pass.**
That is a real, honest outcome of applying an objective gate, not a
sign anything went wrong.

## The gate

`analysis/selection.py::SelectionCriteria`, four thresholds chosen and
written down before being applied to any result:

| Criterion | Default | What it guards against |
|---|---|---|
| `min_development_trades` | 30 | A candidate passing on a handful of trades |
| `min_validation_trades` | 15 | The same, for the untouched validation split |
| `min_development_expectancy_r` | 0.0 (must be above) | The larger, older split must show a real edge, not just break even |
| `min_validation_expectancy_r` | 0.0 (must be above) | The edge must show up again, independently, in validation |

A candidate fails outright if it misses any one criterion. This is a
gate, not a weighted score: unlike Phase 6's optimization framework
(which scores and ranks configurations), Phase 8 decides pass or fail.
Every failed criterion is recorded, not just whichever one failed
first, so `evaluate_selection` reports "too few trades" and "losing
money" as the distinct problems they are, rather than one blanket
"failed."

Each threshold traces directly to a specific problem already found in
this program's own real data, not to an abstract standard:

- **The trade-count minimums** come from Phase 7's Breakout and Retest
  result: an 80% win rate and +1.18R expectancy on 5 development trades
  and zero validation trades. That number is not wrong, it is simply
  too small a sample to mean anything, and the gate now says so
  explicitly rather than letting a good-looking number pass unchecked.
- **Requiring validation expectancy above zero, not merely "not much
  worse than development,"** comes from Phase 7's Trend Pullback
  result flipping sign entirely between its own development (+0.15R)
  and validation (-0.53R) splits on the same 180-day window, and from
  the further instability Phase 7 noted against Phase 6's separate
  1-year window for the same family. An edge that only shows up once
  is not distinguishable from noise.

Selection operates only on development and validation data (Phase 7's
`CandidateEvaluation` never carries final-out-of-sample data at all).
A candidate that passes this gate becomes eligible for a one-time
final-out-of-sample evaluation, guarded by
`backtest/final_oos_ledger.py::assert_not_yet_evaluated`. This module
itself never touches or unlocks that step; it only decides eligibility.

## Verification performed

- 7 unit tests (`tests/test_selection.py`): a fully-clearing case
  passes with no failures recorded; each of the four criteria fails
  independently with only its own reason attached (a low development
  trade count does not also report a low validation trade count);
  strong development paired with negative validation still fails
  (mirroring the real Trend Pullback result); a tiny, spectacular-looking
  sample reports all three of its actual problems at once (mirroring
  the real Breakout and Retest result); batch evaluation preserves
  family names and order.
- Full project test suite (469 tests) and `ruff check`/`ruff format --check` pass.
- Zero lines changed in any existing file: `analysis/selection.py` and
  its test file are both new; Phase 7's evaluation framework, every
  Phase 4 candidate family, and `backtest/final_oos_ledger.py` are
  completely untouched.

## Applied to Phase 7's real result

Reusing `docs/phase7_cross_family_xauusd_results.json` directly (no new
data fetched, no code changes to any candidate), with the default
criteria above:

| Family | Result | Failed criteria |
|---|---|---|
| Trend Pullback | FAIL | development trades (22) below minimum (30); validation trades (7) below minimum (15); validation expectancy (-0.5299R) not above minimum |
| Breakout Continuation | FAIL | development trades (24) below minimum (30); validation trades (2) below minimum (15); development expectancy (-0.3774R) not above minimum; validation expectancy (-1.0355R) not above minimum |
| Breakout and Retest | FAIL | development trades (5) below minimum (30); validation trades (0) below minimum (15); validation expectancy (0.0000R) not above minimum |
| Range Rejection | FAIL | development expectancy (-0.2924R) not above minimum; validation expectancy (-0.5144R) not above minimum |
| Liquidity Sweep Reversal | FAIL | development expectancy (-0.0515R) not above minimum; validation expectancy (-0.0173R) not above minimum |

**All five fail.** Range Rejection and Liquidity Sweep Reversal clear
the trade-count bar (they have real samples to judge), and both are
consistent losers in both splits, a genuine negative result, not an
inconclusive one. The other three fail primarily on sample size: there
simply is not enough real history yet in this program's 180-day/1-year
windows to know whether they have an edge either way.

## What this means, and what it doesn't

- **No candidate is unlocked for a final-out-of-sample evaluation.**
  `backtest/final_oos_ledger.py` has not been touched by this phase.
  Its one-time-only guard remains fully available for whichever, if
  any, candidate eventually passes.
- **This is not the same finding for every candidate.** Range Rejection
  and Liquidity Sweep Reversal have real, adequate samples and look
  like straightforward losers on this data. Trend Pullback, Breakout
  Continuation, and Breakout and Retest failed mostly on sample size,
  meaning more real history could plausibly change their outcome
  (in either direction); the two straightforward losers would need a
  much larger shift to change theirs.
- **Nothing has been activated.** `actionable_alerts_enabled` remains
  `False` project-wide, unaffected by this phase's result, per the
  standing instruction to present evidence only and never deploy
  without explicit approval.

## Explicitly NOT done in this phase

No final-out-of-sample evaluation for any candidate (none qualified).
No new real-data fetch (Phase 8 reused Phase 7's existing results). No
demo forward-testing (Phase 9's job, and moot while nothing has passed
selection). No live-alert activation.
