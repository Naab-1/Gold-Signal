# Session checkpoint — 2026-09-02

Durable handoff for the STRATEGY RESEARCH AND REPLACEMENT program. Written
so a future session (with no memory of this one) can resume at Phase 3
without re-deriving anything below.

## Where things stand right now

- **Repo**: `github.com/Naab-1/Gold-Signal`, branch `main`, clean working
  tree, fully pushed. Latest commit: `3c6eb54`.
- **Tests**: 293 passing, `ruff check`/`ruff format --check` clean.
- **Live alerts**: `ModeConfig.actionable_alerts_enabled` defaults to
  `False` for both scalp and daytrade. **No BUY/SELL Telegram alert is
  sent for any instrument or mode right now.** Everything else (NO_TRADE
  logging, scheduler health/recovery notices, missed-setup "do not enter"
  notices, the multi-instrument quote dashboard, catch-up processing) is
  fully live and unaffected.
- **Scheduler**: the external cron-job.org pinger (hitting GitHub's
  `repository_dispatch` endpoint every 5 minutes) is confirmed working —
  verified live via a real triggered run. The GitHub Actions `schedule:`
  cron remains as a redundant backup (confirmed unreliable on its own —
  see below).

## What was completed this session, in order

1. **A+/A/WATCHLIST/NO_TRADE classification** — the user-specified
   Two-Candle Breakout Continuation rule, a one-candle-breakout comparison
   variant, and an independent tier-comparison backtest harness
   (`analysis/tier_comparison.py`) that never blends A+ and A statistics.
2. **Scheduler reliability rewrite** — durable per-candle checkpoints,
   idempotent DB writes and Telegram sends, an actionability check so a
   late-discovered signal is never presented as live, and transition-based
   scheduler health/recovery notices. Root-caused and fixed a real
   production issue: GitHub's `schedule:` cron was firing roughly every
   4 hours, not every 15 minutes (5 consecutive real gaps confirmed via
   GitHub's API before the fix went live).
3. **Multi-instrument expansion, Phase 1** — `InstrumentProfile` for
   XAU/USD, EUR/USD, GBP/USD, USD/JPY; a `Quote` model that cannot
   fabricate a spread by construction; a `quotes` CLI dashboard. Purely
   additive, zero live-alert changes.
4. **Multi-instrument expansion, Phase 2 (backtesting only)** — extended
   `compare-tiers` with `--instrument`/`--variants`, ran real-history A+
   backtests for all four instruments (results below).
5. **Fixed a real measurement bug**: `analysis/frequency.py` never reset
   its per-day signal-count context, so `max_signals_per_session` acted as
   a one-time lifetime cap instead of a daily one. This is why an earlier
   estimate of "~6 signals in 6-7 months" for gold was wrong — it was
   measuring the config's cap value (6), not real frequency. The corrected
   figure is ~99 signals/year. `backtest/engine.py` (used everywhere else)
   already had the correct reset and was never affected.
6. **STRATEGY RESEARCH AND REPLACEMENT, Phase 1 (freeze)** — see
   `docs/baseline_rejection.md`. Real backtests found the current A+ rule's
   out-of-sample expectancy negative or not credibly positive on every
   tested instrument. `actionable_alerts_enabled` now defaults to `False`.
   The old strategy's code/parameters/version are preserved unchanged and
   labeled "LEGACY BASELINE" / "UNVALIDATED" (daytrade has no real backtest
   evidence either way — unproven, not known-bad).
7. **STRATEGY RESEARCH AND REPLACEMENT, Phase 2 (audit)** — see
   `docs/phase2_data_audit.md`. Found and fixed a real gap: trade exits
   (stops/targets/mark-to-market) charged zero spread/slippage, only
   entries did (under-counting cost, never duplicating it). Also added a
   no-lookahead proof for the newer bounded-window walk, which had none.

## Baseline rejection evidence (full detail in `docs/baseline_rejection.md`)

| Instrument | Period | Dev expectancy | OOS expectancy | Verdict |
|---|---|---|---|---|
| XAU/USD | 2 years | −0.215R | −0.018R | Fails, both splits negative |
| EUR/USD | 180 days | −0.200R | +0.373R (n=5) | Fails, larger sample negative |
| GBP/USD | 180 days | −0.304R | −0.515R | Fails, clearest failure |
| USD/JPY | 180 days | −0.115R | +0.091R → −0.030R stressed | Fails, doesn't survive cost stress |

**Important caveat**: all four results above predate the exit-cost fix in
Phase 2's audit (item #7 above). Real numbers are likely slightly worse
than shown. Nobody has re-run these backtests with the fix in place — that
would be a reasonable first task in a future session if a precise updated
baseline number is needed, though it isn't blocking (the rejection
conclusion won't reverse from a cost fix that only adds cost).

## Unresolved issues / known gaps (not blocking, but real)

- `notifications/formatting.py` still hardcodes 2-decimal price display —
  wrong for EUR/USD/GBP/USD (should be ~5) and USD/JPY (should be ~3).
  Not yet a live concern since actionable alerts are off, but will need
  fixing before any instrument's alerts go live.
- Daytrade mode has never been backtested against real history this
  session — its `actionable_alerts_enabled=False` default is precautionary
  (unproven), not evidence-based like scalp's.
- No correlation/combined-portfolio-risk tracking exists yet (EUR/USD vs
  GBP/USD shared USD exposure) — deferred, per the original multi-instrument
  request, to a later phase once candidate strategies exist to correlate.
- The `news_blackout` interface remains a stub (unimplemented), per the
  original project spec.
- `analysis/frequency.py`'s fix was verified with a regression test, but
  its earlier (wrong) output for daytrade mode, if it was ever run, was
  never specifically re-examined — only the scalp-mode narrative was
  corrected in `docs/baseline_rejection.md`.

## Explicit instruction for next session (per the user)

**Do not activate or deploy any experimental strategy.** When resumed,
begin **Phase 3** (chronological data separation: development / validation
/ final untouched out-of-sample, plus walk-forward testing where data
allows) of the STRATEGY RESEARCH AND REPLACEMENT program
(see the full original request in this session's transcript if needed —
not reproduced here in full, but its Phases 3–10 structure is the
governing spec). Then move to **Phase 4** candidate strategies, evaluating
one family at a time, **starting with A. Trend Pullback, then
B. Breakout Continuation** — not building all five families at once.

Each candidate strategy must specify (per the original spec): eligible
instruments, eligible sessions, entry timeframe, higher-timeframe
confirmation, exact entry/stop-loss/TP1-TP2-TP3 logic, net minimum
reward-to-risk, setup expiration, invalidation conditions, spread/volatility
restrictions, news restrictions, cooldown/dedup rules, and a strategy
version. Rules must be frozen and reproducible — no free-form LLM chart
reading for live signals.

## Reusable infrastructure already in place for Phase 3+

- `backtest/split.py::split_cutoff_timestamp`/`split_trades` — chronological
  dev/oos splitting, ratio-configurable. Will need a third split point
  added for the dev/validation/final-oos three-way split Phase 3 requires
  (currently only two-way).
- `analysis/tier_comparison.py`'s `_walk` pattern (bounded 300-candle
  window, matching live production) is the right template for any new
  strategy's walk-forward evaluation — reuse its structure rather than
  writing a fourth walk implementation.
- `instruments.py::InstrumentProfile`/`effective_mode_config` — ready for
  per-instrument strategy parameterization, already proven a no-op for
  XAU/USD's existing defaults.
- `backtest/metrics.py::compute_summary` already produces every metric
  Phase 7 (performance evaluation) asks for per split: win rate, avg
  win/loss R, expectancy, profit factor, drawdown, consecutive losses,
  TP1-3 hit rates, breakeven rate. Session/period/long-vs-short breakdowns
  need grouping the trade list before calling it (see
  `tier_comparison.py`'s per-session grouping for the pattern).
- No regime classifier exists yet (Phase 5) — genuinely new work.
- No parameter-optimization framework exists yet (Phase 6) — genuinely new
  work; note the project's own stated bar: bounded ranges, record every
  config tested, penalize complexity, never optimize on final oos data.
