# Phase 5: Market Regime Classification

**Status: implemented, unit-tested, and benchmark-verified against
synthetic data.** Unlike Phase 4, this phase produces no trading
signals and carries no expectancy of its own — it is a diagnostic
classifier, not a candidate strategy, so there is no "not yet evaluated
against real history" caveat to attach: see **Why this doesn't need the
dev/validation/final-oos split** below for why that discipline doesn't
apply here the way it does to a strategy's backtest.

## What this phase is (and isn't) for

Family D's own spec (Range Rejection) needed the market to be
"objectively classified as ranging," and Family A's spec needed an
"established trend." Both were built with their own minimal,
family-specific check (`is_ranging_market`, `is_established_trend`) —
deliberately, since a full regime classifier wasn't needed for either
family to function and building one mid-family would have tied a much
bigger piece of shared infrastructure to one candidate's timeline.

This phase builds the general-purpose piece those minimal checks always
deferred to: a single classifier that reads the market's condition as
exactly one of five states — `TRENDING`, `RANGING`, `HIGH_VOLATILITY`,
`LOW_VOLATILITY`, `UNCERTAIN` — for **diagnostic use** (e.g. tagging
which regime a candidate strategy's trades occurred in, a future
performance-evaluation phase's job, not this one's). It does not feed
into, gate, or modify any Phase 4 candidate family's entry logic — none
of those five families were touched by this phase.

## Why this doesn't need the dev/validation/final-oos split

Phase 3's chronological data-separation discipline (`backtest/split.py`,
`backtest/final_oos_ledger.py`) exists to stop a *trading rule* from
being fitted to the same data it's judged against. A regime classifier
has no trade outcomes, no expectancy, and nothing here was tuned by
looking at how well it would have performed — it's a descriptive
statistic about price action (how much it's trending, how volatile it
is), verified against independent, well-established indicators (ADX,
Bollinger Band width) rather than against its own trading results. That
verification is a legitimate thing to run on the full available history
without violating the split's purpose, since there is no "overfit to
this data" failure mode for it to protect against.

## Design

### Classification logic (`analysis/regime.py`)

Built from the same two building blocks every Phase 4 candidate family
already uses — EMA separation for trend strength, ATR for volatility —
computed once per call, not five separately-tuned family checks:

1. **Volatility ratio**: current ATR divided by the median ATR over the
   trailing `volatility_lookback` candles.
2. **Trend ratio**: `|EMA_fast - EMA_slow| / current ATR` (identical
   arithmetic to Family A's `is_established_trend`, generalized).
3. **Precedence** (checked in this order, first match wins):
   - `atr_ratio >= high_volatility_atr_ratio` → `HIGH_VOLATILITY`
   - `atr_ratio <= low_volatility_atr_ratio` → `LOW_VOLATILITY`
   - `trend_ratio >= trend_strength_atr_multiple` → `TRENDING`
   - `trend_ratio <= range_strength_atr_multiple` → `RANGING`
   - otherwise → `UNCERTAIN`

Volatility extremes are checked first because a trend/range reading is
unreliable at either volatility extreme — a strong EMA separation
during a volatility spike, or a near-motionless market, isn't a
meaningful trend/range signal either way.

`classify_regime(candles, config)` classifies the market as of the last
candle in the given list — the same "caller passes a bounded window
ending at now" convention every Phase 4 `evaluate_*` orchestrator and
`analysis/candidate_walk.py` already use, so this function itself never
looks beyond what it's given. `classify_regime_series(candles, config)`
classifies every index in one pass (indicators computed once, not
recomputed per index) for backtest/diagnostic use; a dedicated test
proves index *i*'s result never depends on candles after *i*.

### Numeric defaults

| Field | Default | Reasoning |
|---|---|---|
| `ema_fast_period` / `ema_slow_period` | 20 / 50 | Matches the existing project-wide EMA convention |
| `atr_period` | 14 | Matches the existing project-wide ATR convention |
| `volatility_lookback` | 100 | A window long enough to establish a stable "normal" ATR baseline without reaching back so far it blurs genuinely different market periods together |
| `trend_strength_atr_multiple` | 1.0 | Matches Family A's own established-trend floor exactly |
| `range_strength_atr_multiple` | 0.5 | Matches Family D's own "not trending" ceiling exactly |
| `high_volatility_atr_ratio` | 1.5 | Current ATR at 1.5x its recent median is a meaningful expansion |
| `low_volatility_atr_ratio` | 0.6 | Current ATR at 0.6x its recent median is a meaningful contraction |

The gap between `range_strength_atr_multiple` (0.5) and
`trend_strength_atr_multiple` (1.0) is the intentional `UNCERTAIN` band
— the same gray zone already called out in Family D's own
documentation, now formalized as its own explicit classification
outcome rather than left implicit.

### Benchmark comparison (`analysis/regime_benchmark.py`)

Two new, independent indicators were built specifically to check the
classifier against a genuinely different derivation — neither is used
by the classifier itself, and neither is used by any Phase 4 strategy:

- **`indicators/adx.py`**: Wilder's Average Directional Index, +DI, -DI
  — the industry-standard trend-strength indicator, built from
  directional price movement smoothed against true range. Benchmarked
  with the conventional reading (ADX ≥ 25 → trending, ADX ≤ 20 →
  ranging, the 20–25 band its own "no clear trend" reading).
- **`indicators/bollinger.py`**: Bollinger Bands and band width — built
  from close-price standard deviation, a completely different
  statistical basis from ATR's true-range derivation. Benchmarked the
  same way the classifier reads volatility (current width relative to
  its own recent median), but computed independently.

`compare_regime_to_benchmark` measures agreement only over candles
where **both** methods make a non-ambiguous call on that axis (both
call trend/range, or both call high/low volatility) — comparing against
a method's own "no clear signal" reading wouldn't be a meaningful
agreement check.

## Verification performed

- 15 unit tests for ADX (`tests/test_adx.py`): hand-computed directional-move construction, the Wilder-smoothing helper's exact seed/recursion arithmetic, and behavioral checks (ADX > 90 for a clean uptrend, ADX < 20 for a choppy non-trending series, +DI dominant in an uptrend / -DI dominant in a downtrend).
- 6 unit tests for Bollinger Bands (`tests/test_bollinger.py`): config validation, hand-computed band values (including an exact population-standard-deviation calculation), and a wider-band-for-more-volatile-series check.
- 15 unit tests for the classifier (`tests/test_regime.py`): config validation, one engineered scenario per regime (clean uptrend/downtrend → `TRENDING`, flat oscillation → `RANGING`, calm-then-spike → `HIGH_VOLATILITY`, normal-then-calm → `LOW_VOLATILITY`, a mild drift in the gray-zone gap → `UNCERTAIN`), insufficient-history/empty-input handling, and a no-lookahead proof that `classify_regime_series`'s value at index *i* matches calling `classify_regime` on the truncated prefix ending at *i*.
- 4 unit tests for the benchmark comparison (`tests/test_regime_benchmark.py`), using a synthetic series engineered with alternating calm/volatile blocks (a plain stationary random walk, e.g. `MockDataProvider`, never shifts its own volatility, so it can't exercise the volatility axis at all) — asserting agreement above 70% on both axes with a meaningful comparison sample size.
- On that same mixed-regime synthetic series (4,800 M15 candles): **83.1% trend/range agreement with ADX** (n=2,196 comparable candles) and **99.1% volatility agreement with Bollinger Band width** (n=1,082 comparable candles).
- Separately, on a plain stationary random-walk series (`MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)`, 17,281 M15 candles, the same generator used for every Phase 4 family's synthetic scan): **83.2% trend/range agreement with ADX** (n=10,251) — consistent with the mixed-regime result; the volatility axis wasn't exercised at all on this series (0 comparable candles), since a stationary random walk has no genuine volatility regime shift to detect, which is itself the reason the dedicated mixed-regime series above was built for that axis.
- Full project test suite (442 tests) and `ruff check`/`ruff format --check` pass.
- Zero lines changed in any existing file — every file this phase touches (`indicators/adx.py`, `indicators/bollinger.py`, `analysis/regime.py`, `analysis/regime_benchmark.py`, and their four test files) is new; the frozen A+/A-tier baseline and all five Phase 4 candidate families are completely untouched.

## Explicitly NOT done in this phase

This classifier is not wired into any Phase 4 candidate family, does not gate any live or backtested signal, and has not yet been used to tag any candidate's actual trade history by regime — that correlation (which regimes each candidate strategy performs well or badly in) is Phase 7's job (performance evaluation), not this one's. No live-alert activation, no cross-family comparison, no controlled optimization (Phase 6) performed here.
