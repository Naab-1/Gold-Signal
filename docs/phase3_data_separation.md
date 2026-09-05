# Phase 3: chronological data separation

**Status: scaffolding built and tested. No candidate strategy exists yet
(Phase 4 hasn't started), so nothing in this document reports a new
real-data result — it documents the evaluation infrastructure every
Phase 4+ candidate strategy will be run through.**

Per the STRATEGY RESEARCH AND REPLACEMENT program's Phase 3 spec:
"Separate historical data chronologically into development / validation /
final untouched out-of-sample. ... Any adjustment creates a new strategy
version requiring new unseen data. Where sufficient data exist, also
conduct walk-forward testing."

## Split ratios: 70% development / 15% validation / 15% final-out-of-sample

Not an even 50/25/25. This project's own real trade counts, already
measured at the existing 70/30 two-way split (`docs/baseline_rejection.md`),
are the concrete evidence:

| Instrument | Period | Dev trades (70%) | Out-of-sample trades (30%) |
|---|---|---|---|
| XAU/USD | 2 years | 136 | 62 |
| EUR/USD | 180 days | 24 | 5 |
| GBP/USD | 180 days | 22 | 4 |
| USD/JPY | 180 days | 25 | 13 |

`docs/baseline_rejection.md` itself already calls EUR/USD's n=5
out-of-sample sample "not a credible sample size on its own." A 50/25/25
split would take that already-thin 30% and roughly halve it again — EUR/USD
and GBP/USD would land at ~2-3 trades in the final out-of-sample slice,
which is not a verdict, it's noise. 70/15/15 (`backtest/split.py`'s new
`split_cutoff_timestamps`/`split_trades_three_way`) preserves gold's
existing dev/oos boundary — validation is carved out of the old 30%, not
out of development — so the slice Phase 4's candidate-strategy design will
lean on most isn't shrunk any further than necessary.

This is a ratio choice, not a mechanical derivation, and was confirmed with
the user before implementation.

## Walk-forward: built, not yet run against real data

`backtest/walk_forward.py`'s `generate_walk_forward_folds` implements
anchored (expanding) walk-forward folds — each fold's train window is a
strict superset of the previous fold's, validate windows are disjoint and
move strictly forward, and the last fold absorbs any remainder so no
candle is silently dropped. Fully tested (9 tests,
`tests/test_walk_forward.py`) against synthetic data.

**Per-instrument usability, given real confirmed data depth:**

| Instrument | Confirmed depth | Walk-forward usable? |
|---|---|---|
| XAU/USD | 2 years (~173,410 5-min candles) | Yes — enough for a genuine multi-fold walk-forward |
| EUR/USD | 180 days (~51,823 5-min candles) | Not yet — would produce at most 1-2 folds, not equivalent evidence |
| GBP/USD | 180 days (~51,823 5-min candles) | Not yet, same reason |
| USD/JPY | 180 days (~51,823 5-min candles) | Not yet, same reason |

Per the user's explicit decision: **this module is built and tested now,
but deliberately not run against real forex data yet.** A deeper history
pull for the three forex pairs has not been attempted this session (only
180 days was ever fetched for them) — until that's tried, running
walk-forward on their current depth would produce thin, likely-meaningless
numbers reported as if they were real evidence, which this program exists
to avoid.

## The final-out-of-sample ledger: mechanical enforcement, not a trust exercise

`backtest/final_oos_ledger.py` enforces the spec's rule in its own words:
*"After the final out-of-sample test, do not adjust the strategy and
report the same final test as independent evidence. Any adjustment
creates a new strategy version requiring new unseen data."*

`assert_not_yet_evaluated(ledger_path, *, strategy_version, instrument, mode)`
raises `FinalOosAlreadyEvaluatedError` if the exact same
(strategy_version, instrument, mode) triple has already been recorded —
call this immediately before running any final-out-of-sample evaluation
in Phase 4+. A genuine strategy adjustment naturally produces a new
`strategy_version` string, which trivially passes the guard; re-running
the *same* version against final-oos a second time — the exact scenario
the spec warns against — is what gets blocked.

Built now, before any candidate strategy exists, following this project's
own established pattern: `ModeConfig.actionable_alerts_enabled` (Phase 1)
was built as a guardrail before a good strategy existed too, rather than
relying on a future session to remember the rule. The ledger is a
file-based JSON-lines audit trail (`backtest/final_oos_ledger.py`, reusing
`backtest/export.py`'s `to_jsonable` serializer — renamed from private
`_jsonable` to be shared rather than duplicated), not Postgres: this is a
research-time record, not live production state.

`FinalOosEvaluation.dataset_note` (e.g. "180d, TwelveData, fetched
2026-09-05") is recorded for human audit context but is deliberately **not**
part of the guard key — so a deeper future history pull for the same
instrument doesn't retroactively change blocking behavior; it's a
breadcrumb for a future session reasoning about what data a past
evaluation actually used, not a way to bypass the rule.

## Not touched

`analysis/tier_comparison.py`'s existing A+/A-tier comparison keeps using
the original 2-way `split_cutoff_timestamp`/`split_trades` completely
unchanged — confirmed by zero diff to that file and by re-running
`tests/test_tier_comparison.py`/`tests/test_tier_comparison_no_lookahead.py`
after this phase's changes. Phase 3 adds new, additive evaluation
infrastructure; it does not modify any already-completed comparison.
