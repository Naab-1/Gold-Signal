# Baseline strategy rejection

**Status: the current production rule (`strategy/_common.py::evaluate_trend_ema_rsi_atr`,
the "A+" tier, versions `scalp_ema_rsi_atr_v1` / `daytrade_ema_rsi_atr_v1`) is
rejected for actionable live Telegram alerts.** `ModeConfig.actionable_alerts_enabled`
defaults to `False` for this reason. NO_TRADE evaluation, signal persistence,
scheduler catch-up, health/recovery notices, and missed-setup "do not enter"
notices are all unaffected — only the live BUY/SELL Telegram send is suppressed.

This document exists per the explicit instruction: "Document exactly why the
baseline was rejected." The strategy's code, parameters, and version strings
are preserved unchanged (see the "LEGACY BASELINE" docstrings in
`strategy/scalp.py` / `strategy/day_trade.py`) — nothing here should be read
as license to quietly retune this same version to look better; a fix is a
new version, tested on data it has never seen.

## Evidence

All results below use `analysis/tier_comparison.py`'s independent A+ walk
(bounded to the last 300 candles per step, matching what the live bot
actually sees), real TwelveData history, no synthetic/extended data, no
look-ahead. Every number is post-cost (spread + slippage; transaction cost
is 0 in this project's cost model). "Worse-case" doubles/triples spread and
slippage assumptions — see `tier_comparison.py`'s `worse_case_cost_multiplier`.

### XAU/USD (scalp), 2 years, real cost

| Split | Trades | Win rate | Expectancy | Profit factor | Max drawdown | Worst streak |
|---|---|---|---|---|---|---|
| Development | 136 | 35.3% | **−0.215R** | 0.67 | 36.95R | 13 losses |
| Out-of-sample | 62 | 45.2% | **−0.018R** | 0.97 | 8.76R | 8 losses |

Under worse-case costs: development −0.284R, out-of-sample −0.063R (both
get worse). 198 total A+ signals over 2 years (~99/year) — see
"Related finding" below for why this contradicts an earlier, incorrect
"~6 signals in 6-7 months" estimate.

### EUR/USD (scalp), 180 days, real cost

| Split | Trades | Win rate | Expectancy | Profit factor |
|---|---|---|---|---|
| Development | 24 | 37.5% | **−0.200R** | 0.68 |
| Out-of-sample | 5 | 60.0% | +0.373R | 1.93 |

The out-of-sample slice looks positive but is 5 trades — not a credible
sample size on its own, and it disagrees with the much larger development
result. Under worse-case costs, development drops to −0.328R and
out-of-sample to +0.167R.

### GBP/USD (scalp), 180 days, real cost

| Split | Trades | Win rate | Expectancy | Profit factor |
|---|---|---|---|---|
| Development | 22 | 31.8% | **−0.304R** | 0.55 |
| Out-of-sample | 4 | 25.0% | **−0.515R** | 0.31 |

Losing in both splits, the clearest failure of the four instruments.

### USD/JPY (scalp), 180 days, real cost

| Split | Trades | Win rate | Expectancy | Profit factor |
|---|---|---|---|---|
| Development | 25 | 40.0% | **−0.115R** | 0.81 |
| Out-of-sample | 13 | 46.2% | +0.091R | 1.17 |

The best of the four, but the out-of-sample edge flips negative
(−0.030R) under worse-case costs — it doesn't survive a cost-stress test,
which is one of this project's own stated bars for activation.

## Conclusion

Four independent instruments, one shared rule: none clear the bar. Where an
out-of-sample slice looks positive (EUR/USD, USD/JPY), the sample is small
and/or the result doesn't survive worse-case costs. Where the sample is
largest and most trustworthy (development splits, and XAU/USD's full 2-year
history), the result is consistently negative. This is evidence the rule
itself lacks a real edge on this timeframe/instrument combination — not
evidence that any one instrument or time window was unlucky.

## Related finding: the earlier "~6 signals in 6-7 months" estimate was wrong

A bug in `analysis/frequency.py` (fixed, see git history) never reset its
per-day signal counter, so `max_signals_per_session` (6, for scalp) acted as
a one-time lifetime cap across the whole test instead of a daily cap. The
tool was measuring the config's own cap value, not the strategy's real
frequency. The correct figure, from the (unaffected) tier-comparison
methodology above, is ~99 signals/year for XAU/USD scalp — meaning the
original motivation for building an "A"/WATCHLIST tier (to get more signal
opportunities) was based on a false premise. The real problem was never
frequency; it's edge.

## What is NOT affected

- `strategy/classification.py`'s A-tier (two-candle continuation) and the
  one-candle-breakout comparison variant were never enabled for live alerts
  and remain so — their own sample sizes are far too small to evaluate
  (1 trade and 13 trades respectively over gold's 2-year test).
- Scheduler catch-up, idempotent persistence, health/recovery notices, and
  the multi-instrument quote dashboard (Phase 1) are all independent of this
  decision and continue operating normally.
- Historical signals and backtest output files are untouched.

## Reversal condition

Re-enable `actionable_alerts_enabled` for a given mode only when a specific
strategy version has documented, out-of-sample, cost-stress-tested positive
expectancy on that instrument — per the criteria in the
STRATEGY RESEARCH AND REPLACEMENT program (Phase 8 selection requirements).
Re-enabling the *current* rejected version without a genuine rule change
would defeat the purpose of this freeze.
