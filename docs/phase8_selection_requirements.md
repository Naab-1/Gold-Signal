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

## Re-applied to a 2-year extended window

Per the sample-size gap identified above, `docs/phase7_performance_evaluation.md`
was extended with a 2-year XAU/USD run specifically to give Trend
Pullback and Breakout Continuation enough trades to judge. Re-applying
the same, unchanged criteria to that result
(`docs/phase7_cross_family_xauusd_2yr_results.json`):

| Family | Result | Failed criteria |
|---|---|---|
| Trend Pullback | FAIL | development expectancy (-0.1102R) not above minimum; validation expectancy (-0.1721R) not above minimum |
| Breakout Continuation | FAIL | development expectancy (-0.3675R) not above minimum; validation expectancy (-0.3588R) not above minimum |
| Breakout and Retest | FAIL | development trades (11) below minimum (30); validation trades (4) below minimum (15); development expectancy (-0.0490R) not above minimum |
| Range Rejection | FAIL | development expectancy (-0.1108R) not above minimum; validation expectancy (-0.3533R) not above minimum |
| Liquidity Sweep Reversal | FAIL | development expectancy (-0.0870R) not above minimum; validation expectancy (-0.0724R) not above minimum |

**Still all five fail, but the picture is now much clearer.** Trend
Pullback and Breakout Continuation both now clear the trade-count
minimums and fail purely on losing money in both splits, the same
straightforward-loser finding Range Rejection and Liquidity Sweep
Reversal already had. Only Breakout and Retest still fails on sample
size; even 2 years of history produced just 11 development and 4
validation trades, suggesting its setup is rare enough on XAU/USD at
M15 that judging it here would need substantially more history than is
practical to gather.

## What this means, and what it doesn't

- **No candidate is unlocked for a final-out-of-sample evaluation.**
  `backtest/final_oos_ledger.py` has not been touched by this phase.
  Its one-time-only guard remains fully available for whichever, if
  any, candidate eventually passes.
- **Four of five candidates are now confidently-sampled losers, not
  inconclusive results.** Trend Pullback, Breakout Continuation, Range
  Rejection, and Liquidity Sweep Reversal all have adequate trade
  counts in both splits and are negative in both. Only Breakout and
  Retest remains genuinely undecided, and closing that gap would need
  far more real history than a 2-year window provides.
- **Nothing has been activated.** `actionable_alerts_enabled` remains
  `False` project-wide, unaffected by this phase's result, per the
  standing instruction to present evidence only and never deploy
  without explicit approval.

## Applied to the other three instruments: EUR/USD, GBP/USD, USD/JPY

At the user's request, all five candidates were also run against the
other three instruments GoldSignal supports, using the same real
default configurations (with each instrument's own cost profile applied
via `instruments.py::effective_mode_config`) over a 180-day XAU/USD-
equivalent window. Full detail is in
`docs/phase7_other_instruments_180d_results.json`.

**All 15 family/instrument combinations fail selection. None come
close.** The same pattern seen on gold repeats here: Range Rejection
and Liquidity Sweep Reversal have adequate trade counts on every
instrument (142-389 development trades, 28-80 validation trades) and
are negative in every single case, on all three instruments, in both
splits, no exceptions. The other three families (Trend Pullback,
Breakout Continuation, Breakout and Retest) fail purely on sample size
at this 180-day window (the same issue XAU/USD had before its window
was extended to 2 years): none of their 9 family/instrument combinations
reaches even the 30-trade development minimum, the highest being GBP/USD
Trend Pullback at 28. Their signs bounce inconsistently between
positive and negative across instruments and between development and
validation (e.g. EUR/USD Trend Pullback: +0.31R development on 15
trades, then -1.06R validation on a single trade), exactly what noise
looks like on samples this small, not evidence of anything either way.

**No family shows any evidence of working on any instrument.** This
answers the "does this work somewhere else" question directly: no.
Extending the same 2-year treatment already applied to gold would very
likely just reconfirm this with tighter numbers, the same way it did
for XAU/USD's own Trend Pullback and Breakout Continuation results,
not reverse it, given how consistently negative every well-sampled
result already is here.

**Nothing is being incorporated for testing.** Since no candidate
passed selection on any instrument, there is no live or demo alert
change to make. `actionable_alerts_enabled` remains `False`
everywhere, per the standing instruction to present evidence only and
never activate anything without it first passing this gate and then
receiving explicit approval.

## Explicitly NOT done in this phase

No final-out-of-sample evaluation for any candidate (none qualified on
any instrument). No demo forward-testing (Phase 9's job, and moot while
nothing has passed selection). No live-alert activation, on any
instrument, for any family.
