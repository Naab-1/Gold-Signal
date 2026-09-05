# Phase 4, Family A: Trend Pullback

**Status: implemented and unit-tested against synthetic data. Not yet
evaluated against real history at all (see "Next step" below) — this
document is the frozen rule specification, not a performance report.**

Independent of, and never combined with, the frozen A+/A tiers
(`docs/baseline_rejection.md`). `StrategyMode.TREND_PULLBACK` is its own
identity in the data model; nothing about the rejected baseline was
touched building this.

## Rule specification (every field the program's spec requires)

- **Eligible instruments**: all four (XAU/USD, EUR/USD, GBP/USD, USD/JPY) — the rule is ATR-relative throughout and instrument-agnostic by construction. Per-instrument backtest results (a later step) decide what actually works; there's no principled reason to restrict eligibility a priori, especially since the frozen baseline's failure wasn't instrument-specific either.
- **Eligible sessions**: not gated at signal-generation time. Session performance gets measured and reported, not pre-filtered without evidence.
- **Entry timeframe**: M15.
- **Higher-timeframe confirmation**: H1.
- **Exact entry conditions** (all must hold on the same, current closed candle):
  1. An established higher-timeframe trend exists: H1 EMA(20) vs EMA(50) separation `>= trend_strength_atr_multiple * ATR(14)`.
  2. A pullback dip was found: scanning back up to `pullback_lookback_candles` (M15) candles, the most recent candle where RSI(14) reached the counter-trend `pullback_rsi_trigger` level.
  3. The current candle is the *first* one after that dip where RSI crosses back through `pullback_rsi_confirm` (not just any later candle above it — see "Design corrections" below).
  4. The current candle is directional (bullish close>open for BUY, bearish for SELL).
  5. The current candle's close is back beyond EMA(fast) — reclaiming it.
  6. Price is not already extended: `(close - EMA_fast)` (BUY, mirrored for SELL) does not exceed `max_extension_atr_multiple * ATR`.
  7. At least one profit target clears `min_net_reward_r` net of costs.
- **Exact stop-loss logic**: the existing, shared `strategy/stop_loss.py::compute_stop_loss` — ATR-buffer widened by structure when the structural reference is more conservative — with the structural reference being the pullback leg's own extreme (min low / max high from the dip candle to now), the same shared function A+/A-tier already use, no new stop logic invented.
- **TP1/TP2/TP3 logic**: the existing, shared `strategy/targets.py::build_targets`/`candidate_structure_levels`, with a dedicated `structure_lookbacks` field (`(20, 40, 60)` by default) — never mechanically invented, only real structure levels that clear the net-reward bar.
- **Net minimum reward-to-risk**: `min_net_reward_r` (default 1.5).
- **Setup expiration**: `setup_expiration_candles` (default 3) M15 candles after the signal.
- **Invalidation conditions**: price closes back through the pullback structure before entry is filled; setup not filled by the expiration timestamp.
- **Spread and volatility restrictions**: the existing cost-model gate inside `build_targets` — a target must clear net-of-cost reward given `estimated_spread`/`estimated_slippage`/`estimated_transaction_cost`. A live max-spread-quote gate (using `instruments.py`'s `Quote`) is a later-phase (demo forward-testing) concern, not built here.
- **News restrictions**: not implemented — matches the existing, already-documented project-wide gap (`docs/phase2_data_audit.md`); not invented per-strategy.
- **Cooldown and deduplication rules**: `cooldown_minutes` (default 60) and `max_signals_per_session` (default 3), enforced via the same `EvaluationContext` mechanism A+ already uses.
- **Strategy version**: `trend_pullback_v1`.

## Numeric defaults

| Field | Default |
|---|---|
| `trend_strength_atr_multiple` | 1.0 |
| `pullback_rsi_trigger` | 40 (mirrors 60 for downtrends) |
| `pullback_rsi_confirm` | 50 |
| `pullback_lookback_candles` | 20 |
| `max_extension_atr_multiple` | 1.5 |
| `structure_lookbacks` | (20, 40, 60) |
| `min_net_reward_r` | 1.5 |
| `cooldown_minutes` | 60 |
| `max_signals_per_session` | 3 |
| `setup_expiration_candles` | 3 |

Configurable via `GOLDSIGNAL_TRENDPULLBACK_*` env vars (family-specific) and `GOLDSIGNAL_TRENDPULLBACK_*` mode-config vars (timeframes/indicator periods/cost estimates — a separate, independent `ModeConfig`, not shared with Scalp or Day-Trade).

## Design corrections found during implementation (not silently folded in)

Three real gaps were found and fixed before this rule was ever run against data — each is exactly the kind of frozen-rule detail this program exists to get right before trusting a backtest number:

1. **"Somewhere in the lookback window" is not "the pullback has ended."** An initial draft checked the three confirmation conditions independently, with no link back to *which* dip they were confirming — every RSI up-tick after any old dip would re-qualify. Fixed: confirmation must be the *first* candle after the dip where RSI crosses back, verified by scanning every candle strictly between the dip and now and confirming none of them already crossed (`is_first_rsi_crossing`). Proven by a dedicated test (`test_does_not_refire_on_a_later_uptick_after_the_first_crossing`).
2. **The stop's structural reference is derived from the dip itself**, not a second, separately-tuned lookback window — avoiding a second magic number and keeping the stop tied to the actual pullback leg being traded.
3. **A real bug caught by testing, not just review**: an initial version also checked extension against the pullback's own swing low/high (mirroring `compute_stop_loss`'s "ATR vs. structural, take the more conservative" shape). A synthetic-data scan showed this rejected **every single otherwise-confirmed setup (0 out of 53)** — the distance from a reclaim candle back to the pullback's *own low* is large by definition (that's what a retracement is), so this measured the depth of the retracement the rule already requires, not extension at all. Removed; the extension gate now checks only distance from the fast EMA, which the same scan confirmed works correctly (27 BUY + 25 SELL signals produced, all with sane entry/stop/target ordering).

## Config architecture

A dedicated `TrendPullbackConfig` (`strategy/candidates/trend_pullback.py`), not more fields bolted onto the shared `ModeConfig` (which already mixes A+ and A-tier fields with no natural stopping point). The generic/shared half (timeframes, indicator periods, ATR-stop multiplier, cost estimates) is a separate, independently-loaded `ModeConfig` (`config.py::load_trend_pullback_mode_config`), reusing the existing generic `load_mode_config` machinery — zero new fields or validation branches on `ModeConfig` itself. This establishes one clean, scalable convention for the remaining candidate families.

## Verification performed

- 25 unit tests (`tests/test_trend_pullback.py`): config loading/validation, every pure predicate (including the ordered-dip-then-first-crossing fix and its non-refire proof), a full synthetic scan producing both BUY and SELL with sane entry/stop/target ordering, distinct (non-blanket) NO_TRADE reasons, cooldown enforcement, and the `Strategy`-protocol wrapper.
- 3 tests for the new generic candidate-walk harness (`tests/test_candidate_walk.py`), including a dedicated no-lookahead proof (truncated-vs-full-history agreement), mirroring `tests/test_backtest_no_lookahead.py`'s and `tests/test_tier_comparison_no_lookahead.py`'s existing pattern.
- Zero lines changed in any frozen A+/A-tier file (`strategy/_common.py`, `strategy/classification.py`, `strategy/continuation.py`, `strategy/scalp.py`, `strategy/day_trade.py`).

## Explicitly NOT done in this phase

- **No real-history evaluation at all yet.** This phase built and unit-tested the rule; running it against real XAU/USD development-slice data (never validation or final-out-of-sample) is the next concrete step, kept separate so a real-data run doesn't get bundled into "did the code work" review.
- **No comparison against other candidate families.** Family B (Breakout Continuation) hasn't been designed yet — comparing Trend Pullback's validation-split performance against other families happens once more than one family exists, per the program's own phase ordering.
- **No final-out-of-sample evaluation.** Gated behind `backtest/final_oos_ledger.py`'s guard, which only makes sense once a candidate is actually being considered for selection, not during initial rule design.
