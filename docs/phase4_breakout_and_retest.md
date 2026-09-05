# Phase 4, Family C: Breakout and Retest

**Status: implemented and unit-tested against synthetic data. Not yet
evaluated against real history at all** — same discipline as Families A
and B: this document is the frozen rule specification, not a performance
report.

## Why this family needed extra care

Per the user's own instruction: *"Preserve as a highly selective
candidate. Do not assume it is automatically superior."* This matters
more here than for any other family, because the **frozen, rejected** A+
baseline (`strategy/_common.py`) also used a breakout-and-retest
confirmation — mixed together with its own EMA/RSI trend filters, which
may well be why it failed, not the breakout-and-retest concept itself.
This is a genuinely fresh, independently-tuned candidate: its own config,
own timeframes, own thresholds, its own selectivity rules — not a
repackage of the rejected rule under a new name, which would prove
nothing about whether breakout-and-retest itself has an edge.

## Rule specification

- **Eligible instruments**: all four, same reasoning as Families A/B.
- **Eligible sessions**: not gated at signal-generation time.
- **Entry timeframe**: M15.
- **Higher-timeframe confirmation**: H1. (Matches Trend Pullback's cadence — a genuine retest needs room to develop, unlike Breakout Continuation's fast 1-2-candle confirmation.)
- **Exact entry conditions**:
  1. A pre-existing level (resistance or support) is found via `level_lookback`, computed strictly before the entire breakout+retest scan window.
  2. Scanning back up to `retest_lookback_candles`, the most recent candle that qualifies as a strong breakout against that level — reusing the frozen `strategy/continuation.py::classify_breakout_candle` **unchanged** (large-enough distance beyond the level, real body, closing near its extreme, not an oversized range).
  3. No candle strictly between the breakout and now already closed back through the level — this is what makes it a genuine *retest*, not a failed breakout that happened to wick back toward the level once. A retest holds beyond the level throughout, wicking into it only at the retest candle itself.
  4. The *current* (most recent) candle is itself the retest-and-reject candle: it wicks back into the level (within `retest_tolerance_atr_fraction * ATR`) but closes back out of it directionally — a rejection at the level, deliberately a **different shape** from Family B's "close beyond the breakout's own close" continuation pattern.
  5. At least one profit target clears `min_net_reward_r` net of costs.
- **Exact stop-loss logic**: the existing, shared `compute_stop_loss`, with the structural reference being the *opposite*-side level from the one broken (support for a BUY breakout, resistance for a SELL breakdown) — the same pattern the frozen A+ rule and Family B both already use.
- **TP1/TP2/TP3 logic**: the existing, shared `build_targets`/`candidate_structure_levels`, dedicated `structure_lookbacks` field.
- **Net minimum reward-to-risk**: `min_net_reward_r` (default 1.5).
- **Setup expiration**: `setup_expiration_candles` (default 3) M15 candles after the signal.
- **Invalidation conditions**: price closes back through the retested level before entry is filled; setup not filled by the expiration timestamp.
- **Spread and volatility restrictions**: the existing cost-model gate inside `build_targets`.
- **News restrictions**: not implemented — matches the existing, documented project-wide gap.
- **Cooldown and deduplication rules**: `cooldown_minutes` (default 60) and `max_signals_per_session` (default 3), via the same `EvaluationContext` mechanism every strategy in this project uses.
- **Strategy version**: `breakout_and_retest_v1`.

## What makes this genuinely different from Family B and from the frozen A+ rule

| | Frozen A+ (rejected) | Family B (Breakout Continuation) | Family C (this one) |
|---|---|---|---|
| Confirmation shape | Breakout + retest scan (`indicators/structure.py::breakout_and_retest`), gated behind separate EMA/RSI trend filters | Immediate 2-candle continuation: confirmation candle closes *beyond the breakout's own close* | Confirmation candle *wicks into* the level and *rejects* it — the opposite shape from continuation |
| Timeframe | M5/M15 (scalp) or M15/H1 (day-trade) | M5/M15 | M15/H1 |
| Trend pre-filter | Yes (EMA/RSI alignment required) | No | No |
| Invalidation check | Implicit in the scan window | N/A (immediate) | Explicit: any close-through between breakout and retest invalidates the setup |

The retest-and-reject shape and the explicit invalidation check are the two genuinely new pieces of logic in this family (`is_retest_and_reject`, `is_invalidated_before_retest`) — everything else reuses already-validated shared math.

## A real gap found and fixed via the same synthetic-scan discipline

The first working version produced correct BUY/SELL signals immediately (44 signals, sane trade parameters) — but a synthetic scan showed 2,881 of 2,897 NO_TRADE outcomes falling into one blanket `"no_qualifying_retest_setup"` reason, because the code tried both directions in a loop and lost track of which specific stage failed once a `continue` moved on to the other direction. Fixed by tracking the furthest-progressed failure across both directions and reporting that specifically (`no_breakout_candle_found_either_direction` / `breakout_found_but_not_yet_retested` / `breakout_invalidated_before_retest` / `breakout_confirmed_but_retest_not_yet_rejected`) — re-running the same scan afterward produced identical signal counts (confirming this was purely a diagnostic improvement, not a logic change) with reasons now well-distributed across all four categories.

## Verification performed

- 16 unit tests (`tests/test_breakout_and_retest.py`): config, the invalidation check (both directions), the retest-and-reject shape (touch/no-touch, close-through, non-directional, both directions), a full synthetic scan producing both BUY and SELL with sane trade parameters, specific (not blanket) NO_TRADE reasons, cooldown enforcement, and the `Strategy`-protocol wrapper.
- `analysis/candidate_walk.py` (built for Family A) reused with zero modification — confirmed directly against the manual scan's exact trade count (44).
- Zero lines changed in any frozen A+/A-tier file, and zero lines changed in Family A's or Family B's own files.

## Explicitly NOT done in this phase

Same as Families A and B: no real-history evaluation yet, no comparison against the other families, no final-out-of-sample evaluation.
