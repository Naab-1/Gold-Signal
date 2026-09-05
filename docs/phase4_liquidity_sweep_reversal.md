# Phase 4, Family E: Liquidity Sweep and Reversal

**Status: implemented and unit-tested against synthetic data. Not yet
evaluated against real history at all** — same discipline as Families A
through D: this document is the frozen rule specification, not a
performance report.

This is the last of the five originally-specified candidate families.

## Why this family needed extra care

Per the user's own instruction, this family must be **"mathematically
defined... no vague visual or smart-money terminology."** "Liquidity
sweep" is a term that, in informal trading discussion, often carries
unfalsifiable baggage about institutional intent ("smart money hunting
retail stops"). None of that is encoded here. This module defines
exactly one thing, checkable from OHLC alone: a single candle whose
high (or low) exceeds a prior swing extreme by a meaningful margin,
then closes back beyond that same level by a meaningful margin, on a
directional candle. That is the entire rule — a specific, falsifiable
candle shape, not a narrative about who caused it.

## Rule specification

- **Eligible instruments**: all four, same reasoning as every prior family — the rule is ATR-relative throughout and instrument-agnostic by construction.
- **Eligible sessions**: not gated at signal-generation time.
- **Entry timeframe**: M5.
- **Higher-timeframe confirmation**: M15 (matches Family B's cadence). Not actually used by this family's mechanics — the sweep-and-reversal shape is entirely single-timeframe, the same precedent Family B (Breakout Continuation) already established for a timeframe field that exists to satisfy the shared `ModeConfig`/`Strategy` Protocol shape but isn't read.
- **Exact entry conditions** (`is_liquidity_sweep_reversal`, checked on the current candle only):
  1. A prior swing extreme (resistance/support) is found via `recent_swing_levels` over `sweep_lookback` candles, excluding the current candle so the level isn't computed using the very bar it's meant to test.
  2. The current candle's high (SELL) / low (BUY) exceeds that level by at least `sweep_min_atr_multiple * ATR` — a genuine overshoot, not noise.
  3. The current candle's close is back beyond the level by at least `reversal_min_atr_multiple * ATR` — a decisive reversal, not a bare graze back across the line.
  4. The candle is directional in the reversal direction (bearish close for a SELL sweep of a high, bullish close for a BUY sweep of a low).
  5. At least one profit target clears `min_net_reward_r` net of costs.
- **Exact stop-loss logic**: the existing, shared `compute_stop_loss`, with the structural reference being **the sweep's own extreme** (the current candle's high for a SELL, low for a BUY) plus `stop_buffer_atr_fraction * ATR` — not the older swing level (already exceeded by definition), and not the opposite side (unlike Families B/C). If price later re-exceeds the exact wick that produced the sweep, the reversal thesis is invalidated.
- **TP1/TP2/TP3 logic**: the existing, shared `build_targets`/`candidate_structure_levels`, dedicated `structure_lookbacks` field.
- **Net minimum reward-to-risk**: `min_net_reward_r` (default 1.5).
- **Setup expiration**: `setup_expiration_candles` (default 3) M5 candles after the signal.
- **Invalidation conditions**: price re-exceeds the swept extreme before entry is filled; setup not filled by the expiration timestamp.
- **Spread and volatility restrictions**: the existing cost-model gate inside `build_targets`.
- **News restrictions**: not implemented — matches the existing, documented project-wide gap.
- **Cooldown and deduplication rules**: `cooldown_minutes` (default 30) and `max_signals_per_session` (default 4), via the same `EvaluationContext` mechanism every strategy in this project uses.
- **Strategy version**: `liquidity_sweep_reversal_v1`.

## Numeric defaults (for review, not silently baked in)

| Field | Default | Reasoning |
|---|---|---|
| `sweep_lookback` | 20 | Matches the lookback convention Families C and D use for their own level detection |
| `sweep_min_atr_multiple` | 0.15 | Small on purpose — a sweep is characteristically a wick, not a full breakout candle; this just filters out noise-level overshoots |
| `reversal_min_atr_multiple` | 0.10 | Smaller than the sweep distance — the reversal only needs to be decisive, not as large as the sweep itself |
| `stop_buffer_atr_fraction` | 0.15 | Matches the scale of Family C/D's own tolerance fields |
| `structure_lookbacks` | `[20, 40, 60]` | Matches the existing multi-lookback target-search convention used by every prior family |
| `min_net_reward_r` | 1.5 | Matches Families A, C, and D's own starting choice |
| `cooldown_minutes` | 30 | Half of Families A/C/D's 60 — sweeps are a faster M5 pattern, matching Family B's own cooldown scale |
| `max_signals_per_session` | 4 | Matches Family B's own session cap |
| `setup_expiration_candles` | 3 | Matches existing convention |

## What makes this genuinely different from Families C and D

| | Family C (Breakout and Retest) | Family D (Range Rejection) | Family E (this one) |
|---|---|---|---|
| Precondition | A qualifying breakout candle (`classify_breakout_candle`) occurred earlier and hasn't been invalidated | Market validated as a bounded, non-trending range | None — no regime or prior-candle qualification required |
| Level ever broken? | Yes, on an earlier candle; the *retest* is the test | No — price only wicks within tolerance, never actually breaks it | Yes, on the *same* candle being evaluated |
| Timing | Two distinct candles: the qualifying breakout, then a later retest | One candle: the boundary touch itself | One candle: the overshoot and the reversal both happen on it |
| Stop-loss reference | The *opposite* side's level | The *same* boundary just rejected | The sweep candle's *own* wick extreme |

The single-candle overshoot-then-reverse shape (`is_liquidity_sweep_reversal`) is the one genuinely new piece of logic in this family — everything else (cooldown/session-limit via `EvaluationContext`, cost-model gate, target/stop construction) reuses already-validated shared math.

## Verification performed

- 15 unit tests (`tests/test_liquidity_sweep_reversal.py`): config (including the new sweep/reversal distance fields), `is_liquidity_sweep_reversal` (both directions: true case, no-overshoot case, insufficient-reversal case, non-directional case), a full synthetic scan producing both BUY and SELL with sane trade parameters, specific (not blanket) NO_TRADE reasons, cooldown enforcement, and the `Strategy`-protocol wrapper.
- `analysis/candidate_walk.py` (built for Family A) reused with zero modification.
- A synthetic `MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)` scan with loosened thresholds over 180 days of M5/M15 candles produced 109 BUY and 101 SELL signals out of ~8,000 evaluated candles — a meaningfully rarer setup than Families C/D, consistent with a single-candle pattern requiring both a genuine overshoot and a decisive reversal at once; NO_TRADE reasons were dominated by `no_sweep_and_reversal_confirmed_either_direction` (expected, since most candles simply don't form this specific shape) alongside `insufficient_candle_history` during warmup — no single reason masking a diagnostic gap of the kind found and fixed in Family C.
- Full project test suite (408 tests) and `ruff check`/`ruff format --check` pass.
- Zero lines changed in any frozen A+/A-tier file, and zero lines changed in Families A, B, C, or D's own files — `git diff --stat` confirms only additive entries in `config.py` (new mode-defaults dict + loader), `models/signal.py` (new enum member), and `notifications/formatting.py` (new label).

## Explicitly NOT done in this phase

Same as every prior family: no real-history evaluation yet, no comparison against the other families, no final-out-of-sample evaluation, no live-alert activation.

## Phase 4 is now complete

All five originally-specified candidate families (A: Trend Pullback, B: Breakout Continuation, C: Breakout and Retest, D: Range Rejection, E: Liquidity Sweep and Reversal) are built, unit-tested against synthetic data, and verified to run through the shared `analysis/candidate_walk.py` harness with zero modification. None has been evaluated against real history, compared against another, or had its live alerts activated. Phases 5 through 10 (market-regime classification, controlled optimization, performance evaluation, selection requirements, demo forward-testing, and current live communication rules) remain entirely unbuilt.
