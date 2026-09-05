# Phase 4, Family D: Range Rejection

**Status: implemented and unit-tested against synthetic data. Not yet
evaluated against real history at all** — same discipline as Families A,
B, and C: this document is the frozen rule specification, not a
performance report.

## Why this family needed a design decision the others didn't

This family's own spec requires the market to be "objectively
classified as ranging" before fading a boundary touch. Building a
complete, benchmark-compared 5-way market-regime classifier
(TRENDING / RANGING / HIGH_VOLATILITY / LOW_VOLATILITY / UNCERTAIN) is
Phase 5's job, not Phase 4's — and building it now, mid-family, would
mean tuning and validating a much bigger piece of shared infrastructure
under one candidate's timeline, with no other family yet needing it.

Instead this module implements only the minimal, family-specific check
it actually needs: confirmation-timeframe EMA fast/slow separation
*below* a ceiling (`is_ranging_market`) — the mirror image of Family
A's own `is_established_trend` **floor** check, reusing the identical
EMA-separation-vs-ATR arithmetic with the inequality flipped. This is
the same precedent Family A itself set: its "is there an established
trend" check was always a simple, family-owned predicate, never
promoted into a shared "trend classifier". The complete, benchmark-
compared regime classifier remains a distinct, future piece of work.

## Rule specification

- **Eligible instruments**: all four, same reasoning as Families A/B/C — the rule is ATR-relative throughout and instrument-agnostic by construction.
- **Eligible sessions**: not gated at signal-generation time.
- **Entry timeframe**: M15.
- **Higher-timeframe confirmation**: H1 (matches Families A and C — range identification and the "not trending" check both benefit from more noise-filtering than a 5-minute cadence).
- **Exact entry conditions**:
  1. A range is identified via `recent_swing_levels` over `range_lookback` candles (resistance = max high, support = min low), excluding the current candle so the range isn't computed using the very bar it's meant to confirm.
  2. The range's width, in ATR terms, sits between `min_range_width_atr_multiple` and `max_range_width_atr_multiple` — wide enough to be a real range rather than noise, narrow enough that its boundaries stay meaningful.
  3. The confirmation-timeframe EMA fast/slow separation is **below** `max_trend_strength_atr_multiple * ATR` — i.e. NOT strongly trending (`is_ranging_market`), directly implementing this family's own "do not use it during a strong trend" requirement.
  4. The *current* candle touches a range boundary (within `rejection_tolerance_atr_fraction * ATR`) and rejects it directionally: BUY when support is touched and the candle closes back up and out of it; SELL when resistance is touched and the candle closes back down and out of it (`is_range_boundary_rejection`) — the same touch/reject/directional shape Family C uses at a *broken* level, applied here to a range boundary under a "not trending" precondition instead of a "just broke out" precondition. Kept as its own, independently-named copy rather than an import from Family C's module, since each family's logic is designed, tuned, and evaluated independently.
  5. At least one profit target clears `min_net_reward_r` net of costs.
- **Exact stop-loss logic**: the existing, shared `compute_stop_loss`, with the structural reference being the **rejected boundary itself** (not the opposite side, unlike Families B/C) — if price later breaks through the boundary it just rejected, the range-rejection thesis is invalidated, so the stop belongs just beyond that same level.
- **TP1/TP2/TP3 logic**: the existing, shared `build_targets`/`candidate_structure_levels`, dedicated `structure_lookbacks` field; the opposite range boundary naturally surfaces as a candidate level.
- **Net minimum reward-to-risk**: `min_net_reward_r` (default 1.5).
- **Setup expiration**: `setup_expiration_candles` (default 3) M15 candles after the signal.
- **Invalidation conditions**: price closes back through the rejected boundary before entry is filled; setup not filled by the expiration timestamp.
- **Spread and volatility restrictions**: the existing cost-model gate inside `build_targets`.
- **News restrictions**: not implemented — matches the existing, documented project-wide gap.
- **Cooldown and deduplication rules**: `cooldown_minutes` (default 60) and `max_signals_per_session` (default 3), via the same `EvaluationContext` mechanism every strategy in this project uses.
- **Strategy version**: `range_rejection_v1`.

## Numeric defaults (for review, not silently baked in)

| Field | Default | Reasoning |
|---|---|---|
| `range_lookback` | 20 | Matches the lookback convention Family C uses for its own level detection |
| `min_range_width_atr_multiple` | 1.5 | A range narrower than this is indistinguishable from noise around a single price |
| `max_range_width_atr_multiple` | 6.0 | Wide enough to allow a real range, narrow enough that both boundaries stay meaningfully "the same range" |
| `max_trend_strength_atr_multiple` | 0.5 | A ceiling clearly below Trend Pullback's own 1.0 floor for "established trend" — the gap between 0.5 and 1.0 is an intentional gray zone counted as neither ranging nor established-trending |
| `rejection_tolerance_atr_fraction` | 0.25 | Matches Family C's own retest tolerance |
| `structure_lookbacks` | `[20, 40, 60]` | Matches the existing multi-lookback target-search convention used by every prior family |
| `min_net_reward_r` | 1.5 | Matches Families A and C's own starting choice |
| `cooldown_minutes` | 60 | One H1 confirmation bar's worth |
| `max_signals_per_session` | 3 | Conservative, matching Families A and C |
| `setup_expiration_candles` | 3 | Matches existing convention |

## What makes this genuinely different from Family C

| | Family C (Breakout and Retest) | Family D (this one) |
|---|---|---|
| Precondition | A qualifying breakout occurred and hasn't been invalidated | The market is validated as a bounded, non-trending range |
| Level touched | A *broken* level, retested from the breakout side | A range boundary that has never been broken |
| Trend filter | None | Explicit ceiling: reject if the confirmation timeframe is trending too strongly |
| Stop-loss reference | The *opposite* side's level | The *same* boundary just rejected |

## Verification performed

- 21 unit tests (`tests/test_range_rejection.py`): config (including the new min/max-width-relationship validation), `is_valid_range_width`, `is_ranging_market` (both trend directions), `is_range_boundary_rejection` (touch/no-touch, close-through, non-directional, both directions), a full synthetic scan producing both BUY and SELL with sane trade parameters, specific (not blanket) NO_TRADE reasons, cooldown enforcement, and the `Strategy`-protocol wrapper.
- `analysis/candidate_walk.py` (built for Family A) reused with zero modification.
- A synthetic `MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)` scan with loosened thresholds over 180 days of M15/H1 candles produced 1,186 BUY and 1,112 SELL signals with a well-distributed set of NO_TRADE reasons (`no_boundary_rejection_confirmed_either_direction`, `market_trending_too_strongly`, `range_width_out_of_bounds`, `insufficient_candle_history`, `no_target_clears_minimum_net_reward_after_costs`) — no single blanket reason dominating, so no repeat of Family C's original diagnostic gap.
- Full project test suite (393 tests) and `ruff check`/`ruff format --check` pass.
- Zero lines changed in any frozen A+/A-tier file, and zero lines changed in Families A, B, or C's own files — `git diff --stat` confirms only additive entries in `config.py` (new mode-defaults dict + loader), `models/signal.py` (new enum member), and `notifications/formatting.py` (new label).

## Explicitly NOT done in this phase

Same as Families A, B, and C: no real-history evaluation yet, no comparison against the other families, no final-out-of-sample evaluation. The full 5-way market-regime classifier remains unbuilt and is deferred to its own future phase.
