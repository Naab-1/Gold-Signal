# Phase 2: Data and backtesting-engine audit

Per the STRATEGY RESEARCH AND REPLACEMENT program's Phase 2 checklist.
Each item below states what was verified, where the automated test(s)
live, and what (if anything) was fixed as a result.

## 1. OHLC values and price scale

`data/validation.py::_malformed_reasons` rejects non-finite values,
`high < low`, `open`/`close` outside `[low, high]`, negative volume, and
non-positive close. All six paths are now covered in
`tests/test_validation.py` (three were previously untested: non-finite,
`open` out of range, non-positive close — added this session).
Price-scale correctness per instrument is handled separately by
`instruments.py::InstrumentProfile` (decimal precision, pip/tick size),
verified in `tests/test_instruments.py`.

## 2. Candle timestamps and time zones

`TwelveDataProvider` converts every candle's exchange-local timestamp to
UTC before constructing a `Candle` (`tests/test_twelvedata_provider.py`);
`Candle`/`Quote` both reject non-UTC timestamps at construction
(`utils/time.py::require_utc`). The quotes dashboard displays both UTC and
Africa/Accra time (`tests/test_quotes_dashboard_report.py`).

## 3. Missing and duplicate candles

`validate_candles` detects and reports gaps (without dropping surrounding
data) and drops exact-duplicate timestamps. Covered in
`tests/test_validation.py::test_gap_reported_but_not_dropped` /
`test_duplicate_timestamp_dropped`.

## 4. Fully closed candle identification

A trailing candle whose close time is after `now` is dropped before
anything downstream sees it (`validate_candles`'s incomplete-candle trim,
`tests/test_validation.py`). The live catch-up scan and both backtest
walks (`backtest/engine.py`, `analysis/tier_comparison.py`) independently
enforce "only evaluate a candle once `now` is at or past its close" —
covered by `tests/test_catchup.py::test_still_forming_candle_is_never_yielded`.

## 5. Bid/ask and spread treatment

`models/quote.py::Quote` structurally cannot represent a fabricated spread
(bid/ask must arrive together; mid/spread must be derived from them when
present) — `tests/test_quote.py`. Where a provider doesn't supply bid/ask
(confirmed true for TwelveData's `/quote` on this project's tier), that's
rendered as "not supplied by this provider," never a synthesized value.

## 6. Pip, point, tick, and decimal definitions

Defined per instrument in `instruments.py::InstrumentProfile`
(`pip_size`, `tick_size`, `decimal_precision`, `contract_size`) —
`tests/test_instruments.py`. Not yet consumed by position-sizing (no
position sizing exists in this project yet — signal-only, per the
project's original safety constraint) or by live alert formatting
(`notifications/formatting.py` still hardcodes 2 decimal places; tracked
as a known gap, not yet a live-alert concern since actionable alerts are
currently disabled — see `docs/baseline_rejection.md`).

## 7. Slippage and transaction-cost calculations

`strategy/cost_model.py::CostEstimate`/`net_reward_r` — unit-tested,
shared identically between live signal generation and every backtest path
(single source of truth, not duplicated per the project's own design
principle).

## 8. Entry timing

Every fill is simulated at the *next* candle's open, never the signal
candle's own close (`backtest/engine.py::entry_fill_price`,
`tests/test_backtest_engine.py`). This applies uniformly across
`generate_signals_walk_forward` and `tier_comparison.py`'s `_walk`.

## 9. Stop-loss and take-profit calculations

`strategy/stop_loss.py::compute_stop_loss` (ATR-buffer widened by
structure) and `strategy/targets.py::build_targets` are unit-tested and
shared by every strategy tier (A+, A, one-candle-breakout) — no per-tier
duplicate implementation to drift out of sync.

## 10. Conservative handling when SL and TP occur inside the same candle

Already implemented and tested before this audit:
`backtest/engine.py::simulate_trade_management` checks the stop *before*
any target within the same candle, so a same-candle collision is always
resolved as a loss, never an optimistic win —
`tests/test_backtest_engine.py::test_same_candle_collision_stop_wins_conservatively`.

## 11. No use of future candles / no look-ahead bias

`generate_signals_walk_forward` (the older, unbounded walk) already had a
dedicated proof: `tests/test_backtest_no_lookahead.py` runs the same
history truncated and un-truncated and asserts every truncated-run trade
is byte-identical in the full run. **`analysis/tier_comparison.py`'s
newer, bounded-300-candle-window `_walk` — which now backs every
real-history backtest this project produces — had no equivalent
dedicated test; added this session**
(`tests/test_tier_comparison_no_lookahead.py`, passed on first run).

## 12. No survivorship or selection leakage

**Not directly applicable in this project's current form.** Survivorship
bias classically applies to backtesting a *basket* of instruments selected
because they still exist today (e.g. testing only S&P 500 constituents
that didn't go bankrupt). This project trades a fixed, pre-declared list
of four continuously-traded major FX/metal pairs (XAU/USD, EUR/USD,
GBP/USD, USD/JPY) — none of which can "de-list" or be dropped from
history for surviving/failing, and no instrument has ever been excluded
from a backtest based on its own performance. This will need revisiting
only if the instrument list is ever chosen *based on* which pairs already
looked good historically — it was not: the four were fixed by the user's
own request before any backtest ran.

## 13. No duplicated spread or costs

**Verified, and a real (different) gap found and fixed as a result of
checking this specifically.** Spread is never charged twice — but exits
(stop touches, target touches, and mark-to-market) were charging *zero*
spread/slippage, only entries were. This under-counted real round-trip
cost rather than duplicating it. Fixed: `backtest/engine.py` gained
`exit_fill_price` (the same adverse half-spread+slippage adjustment
`entry_fill_price` already applied, mirrored on the way out) and
`simulate_trade_management` now accepts `estimated_spread`/
`estimated_slippage` (default `0.0`, so every pre-existing test — which
uses 0-cost fixtures — is unaffected; new tests specifically added for
non-zero cost cases). See `tests/test_backtest_engine.py`'s new
"Exit-side spread/slippage cost" section, including
`test_exit_cost_is_charged_once_not_duplicated`, which directly proves
the fix adds exactly one half-spread's worth of cost, not two.

**Consequence for every backtest run so far this session**: real
performance is very likely slightly *worse* than what was reported in
`docs/baseline_rejection.md` — that document's numbers were produced
before this fix and did not charge exit-side spread/slippage at all. The
baseline was already shown to lose money without this cost; this finding
does not change that conclusion, it reinforces it. Any future
strategy-replacement backtest should be run with this fix in place
(already true — it's committed).

## Not yet covered (explicitly deferred)

- **News restrictions**: the project's `news_blackout` interface (from the
  original spec) remains a documented stub, not implemented — no
  automated test exists because there is no real behavior to test yet.
- **Position sizing**: does not exist in this project (signal-only, by
  design) — nothing to audit.
- **Correlation/combined-portfolio risk** (EUR/USD vs GBP/USD shared USD
  exposure): not yet built; part of a later phase of the strategy-research
  program, once candidate strategies exist to correlate.
