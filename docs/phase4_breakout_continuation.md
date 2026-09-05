# Phase 4, Family B: Breakout Continuation

**Status: implemented and unit-tested against synthetic data. Not yet
evaluated against real history at all** — same discipline as Family A
(Trend Pullback): this document is the frozen rule specification, not a
performance report.

Independent of, and never combined with, the frozen A+/A tiers or with
Family A. `StrategyMode.BREAKOUT_CONTINUATION` is its own identity.

## Rule specification

- **Eligible instruments**: all four (XAU/USD, EUR/USD, GBP/USD, USD/JPY) — same reasoning as Family A: ATR-relative throughout, instrument-agnostic by construction, per-instrument backtest results decide what actually works.
- **Eligible sessions**: not gated at signal-generation time — measured and reported, not pre-filtered without evidence.
- **Entry timeframe**: M5.
- **Higher-timeframe confirmation**: M15. (Faster cadence than Trend Pullback's M15/H1 — a breakout continuation is confirmed over 1-2 candles by design, not a multi-candle recovery.)
- **Exact entry conditions**:
  1. A pre-existing swing level (resistance or support) is found over `level_lookback` candles, computed strictly before both the breakout and confirmation candles.
  2. The second-to-last closed candle qualifies as a breakout candle against that level: closes beyond it by at least `continuation_breakout_min_atr_multiple * ATR`, has a real body of at least `continuation_min_body_ratio` of its total range, closes within `continuation_close_position_ratio` of its high/low extreme (direction-appropriate), and its total range does not exceed `continuation_max_range_atr_multiple * ATR` — this last check is what "reject extreme candles that create late entries" means mechanically: an oversized single-candle range usually means price already moved most of the way before this rule could act on it.
  3. The most recent (current) closed candle confirms it: closes beyond the level, closes beyond the breakout candle's own close (further movement, not just holding), doesn't wick back through the level beyond `confirmation_tolerance_atr_fraction * ATR`, and closes in the breakout's direction.
  4. At least one profit target clears `min_net_reward_r` net of costs.
- **Exact stop-loss logic**: the existing, shared `strategy/stop_loss.py::compute_stop_loss`, with the structural reference being the *opposite*-side level from the one that was broken (support for a BUY breakout, resistance for a SELL breakdown) — the same pattern the frozen A+ rule already used, reused unchanged.
- **TP1/TP2/TP3 logic**: the existing, shared `strategy/targets.py::build_targets`/`candidate_structure_levels`, with a dedicated `structure_lookbacks` field (`(20, 40, 60)` by default).
- **Net minimum reward-to-risk**: `min_net_reward_r` (default 1.5).
- **Setup expiration**: `setup_expiration_candles` (default 3) M5 candles after the signal.
- **Invalidation conditions**: price closes back through the broken level before entry is filled; setup not filled by the expiration timestamp.
- **Spread and volatility restrictions**: the existing cost-model gate inside `build_targets`. A live max-spread-quote gate is a later-phase concern.
- **News restrictions**: not implemented — matches the existing, documented project-wide gap.
- **Cooldown and deduplication rules**: `cooldown_minutes` (default 30) and `max_signals_per_session` (default 4), via the same `EvaluationContext` mechanism every other strategy in this project uses.
- **Strategy version**: `breakout_continuation_v1`.

## Reuse, not re-derivation

The breakout/confirmation candle-shape math (`classify_breakout_candle`/`classify_confirmation_candle`) is imported **unchanged** from the frozen `strategy/continuation.py` — the exact same, already-tested (12 tests in `tests/test_continuation_rule.py`) functions the old A-tier rule used. `BreakoutContinuationConfig`'s four shape-threshold fields are deliberately named to match what `classify_breakout_candle` already expects as a config-shaped argument, so it can be passed directly with no adapter. This is reuse of pure, stateless arithmetic only — the frozen module itself, its orchestration (`classification.py`), and its coupling to the rejected A+/A-tier baseline are never touched.

## Statelessness (a deliberate departure from the old A-tier's design)

The frozen A-tier rule used a stateful `pending` object carried between calls (a breakout candle sets a WATCHLIST state; the *next* call either confirms it or resolves it). This family instead checks, fully self-contained within one evaluation: was `entry_candles[-2]` a qualifying breakout candle (relative to a level computed from candles strictly before it), and does `entry_candles[-1]` confirm it? No state threading is needed. This matches the `Strategy` Protocol's exact shape (no `pending` parameter exists there) and is what allows `analysis/candidate_walk.py`'s generic harness — built for Family A, reused unchanged here — to walk this family with zero modification.

## Verification performed

- 10 unit tests (`tests/test_breakout_continuation.py`): config loading/validation, a full synthetic scan producing both BUY and SELL with sane entry/stop/target ordering (worked correctly on the first implementation attempt — no bugs found this time, unlike Family A's extension-check bug), distinct NO_TRADE reasons, cooldown enforcement, and the `Strategy`-protocol wrapper.
- Zero lines changed in any frozen A+/A-tier file, and zero lines changed in Family A's own files (`strategy/candidates/trend_pullback.py`, its tests, or `docs/phase4_trend_pullback.md`).
- `analysis/candidate_walk.py` (built for Family A) reused with zero modification — confirms the generic-harness design decision from Phase 4's plan actually paid off.

## Explicitly NOT done in this phase

Same as Family A: no real-history evaluation yet, no comparison against Family A (that happens once both are backtested independently), no final-out-of-sample evaluation (gated behind `backtest/final_oos_ledger.py`).
