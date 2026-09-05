"""Market-regime classification (STRATEGY RESEARCH AND REPLACEMENT
program, Phase 5) -- see docs/phase5_market_regime_classification.md
for the full spec and the benchmark comparison against ADX and
Bollinger Band width.

Classifies the market, as of the most recent candle in a given window,
into exactly one of five states: TRENDING, RANGING, HIGH_VOLATILITY,
LOW_VOLATILITY, UNCERTAIN. This is deliberately a distinct, standalone
module from any Phase 4 candidate family's own minimal precondition
check (e.g. Family A's `is_established_trend` floor check, Family D's
`is_ranging_market` ceiling check) -- those are single-purpose gates
embedded in one family's own rule; this is the general-purpose, 5-way,
benchmark-verified classifier the whole program's spec calls for, meant
for diagnostic use (e.g. tagging which regime each backtest trade
occurred in during a future performance-evaluation phase), not as an
input any candidate family's frozen entry logic depends on.

Purely descriptive, not predictive or actionable: this module classifies
what the market IS doing as of now, using only already-closed candles
(no lookahead), and produces no trading signal of its own. Because it
has no expectancy, edge, or trade outcome to overfit, it is not subject
to Phase 3's dev/validation/final-out-of-sample split discipline the
way a candidate strategy's backtest results are -- that discipline
exists to prevent fitting a trading rule to the data it's judged
against, which doesn't apply to a descriptive statistic about the
market itself.
"""

from __future__ import annotations

import os
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from goldsignal.config import ConfigError, _get, _parse_float, _parse_int
from goldsignal.indicators.atr import atr as compute_atr
from goldsignal.indicators.ema import ema as compute_ema
from goldsignal.models.candle import Candle


class MarketRegime(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class RegimeClassifierConfig:
    ema_fast_period: int
    ema_slow_period: int
    atr_period: int
    volatility_lookback: int
    trend_strength_atr_multiple: float
    range_strength_atr_multiple: float
    high_volatility_atr_ratio: float
    low_volatility_atr_ratio: float


_REGIME_CLASSIFIER_DEFAULTS: dict[str, str] = {
    "EMA_FAST_PERIOD": "20",
    "EMA_SLOW_PERIOD": "50",
    "ATR_PERIOD": "14",
    "VOLATILITY_LOOKBACK": "100",
    "TREND_STRENGTH_ATR_MULTIPLE": "1.0",
    "RANGE_STRENGTH_ATR_MULTIPLE": "0.5",
    "HIGH_VOLATILITY_ATR_RATIO": "1.5",
    "LOW_VOLATILITY_ATR_RATIO": "0.6",
}


def load_regime_classifier_config(
    env: Mapping[str, str] | None = None,
) -> RegimeClassifierConfig:
    env = os.environ if env is None else env
    prefix = "REGIMECLASSIFIER_"
    defaults = _REGIME_CLASSIFIER_DEFAULTS

    def var(name: str) -> str:
        return f"GOLDSIGNAL_{prefix}{name}"

    config = RegimeClassifierConfig(
        ema_fast_period=_parse_int(
            _get(env, prefix, "EMA_FAST_PERIOD", defaults), var("EMA_FAST_PERIOD")
        ),
        ema_slow_period=_parse_int(
            _get(env, prefix, "EMA_SLOW_PERIOD", defaults), var("EMA_SLOW_PERIOD")
        ),
        atr_period=_parse_int(_get(env, prefix, "ATR_PERIOD", defaults), var("ATR_PERIOD")),
        volatility_lookback=_parse_int(
            _get(env, prefix, "VOLATILITY_LOOKBACK", defaults), var("VOLATILITY_LOOKBACK")
        ),
        trend_strength_atr_multiple=_parse_float(
            _get(env, prefix, "TREND_STRENGTH_ATR_MULTIPLE", defaults),
            var("TREND_STRENGTH_ATR_MULTIPLE"),
        ),
        range_strength_atr_multiple=_parse_float(
            _get(env, prefix, "RANGE_STRENGTH_ATR_MULTIPLE", defaults),
            var("RANGE_STRENGTH_ATR_MULTIPLE"),
        ),
        high_volatility_atr_ratio=_parse_float(
            _get(env, prefix, "HIGH_VOLATILITY_ATR_RATIO", defaults),
            var("HIGH_VOLATILITY_ATR_RATIO"),
        ),
        low_volatility_atr_ratio=_parse_float(
            _get(env, prefix, "LOW_VOLATILITY_ATR_RATIO", defaults),
            var("LOW_VOLATILITY_ATR_RATIO"),
        ),
    )
    _validate_regime_classifier_config(config)
    return config


def _validate_regime_classifier_config(c: RegimeClassifierConfig) -> None:
    if c.ema_fast_period <= 0:
        raise ConfigError("GOLDSIGNAL_REGIMECLASSIFIER_EMA_FAST_PERIOD must be positive")
    if c.ema_slow_period <= c.ema_fast_period:
        raise ConfigError(
            "GOLDSIGNAL_REGIMECLASSIFIER_EMA_SLOW_PERIOD must be greater than "
            "GOLDSIGNAL_REGIMECLASSIFIER_EMA_FAST_PERIOD"
        )
    if c.atr_period <= 0:
        raise ConfigError("GOLDSIGNAL_REGIMECLASSIFIER_ATR_PERIOD must be positive")
    if c.volatility_lookback <= 0:
        raise ConfigError("GOLDSIGNAL_REGIMECLASSIFIER_VOLATILITY_LOOKBACK must be positive")
    if c.trend_strength_atr_multiple <= c.range_strength_atr_multiple:
        raise ConfigError(
            "GOLDSIGNAL_REGIMECLASSIFIER_TREND_STRENGTH_ATR_MULTIPLE must be greater than "
            "GOLDSIGNAL_REGIMECLASSIFIER_RANGE_STRENGTH_ATR_MULTIPLE (the gap between them "
            "is the UNCERTAIN band)"
        )
    if c.range_strength_atr_multiple < 0:
        raise ConfigError(
            "GOLDSIGNAL_REGIMECLASSIFIER_RANGE_STRENGTH_ATR_MULTIPLE must not be negative"
        )
    if c.high_volatility_atr_ratio <= 1.0:
        raise ConfigError(
            "GOLDSIGNAL_REGIMECLASSIFIER_HIGH_VOLATILITY_ATR_RATIO must be greater than 1.0"
        )
    if not (0 < c.low_volatility_atr_ratio < 1.0):
        raise ConfigError(
            "GOLDSIGNAL_REGIMECLASSIFIER_LOW_VOLATILITY_ATR_RATIO must be between 0 and 1.0"
        )


def _classify_at_index(
    idx: int,
    *,
    ema_fast_vals: list[float | None],
    ema_slow_vals: list[float | None],
    atr_vals: list[float | None],
    config: RegimeClassifierConfig,
) -> MarketRegime | None:
    current_atr = atr_vals[idx]
    if (
        ema_fast_vals[idx] is None
        or ema_slow_vals[idx] is None
        or current_atr is None
        or current_atr <= 0
    ):
        return None

    baseline_start = max(0, idx + 1 - config.volatility_lookback)
    baseline_window = [v for v in atr_vals[baseline_start : idx + 1] if v is not None]
    if len(baseline_window) < config.volatility_lookback:
        return None
    baseline_atr = statistics.median(baseline_window)
    if baseline_atr <= 0:
        return None

    atr_ratio = current_atr / baseline_atr
    separation = abs(ema_fast_vals[idx] - ema_slow_vals[idx])
    trend_ratio = separation / current_atr

    # Precedence: volatility extremes are checked first, since trend/range
    # readings are unreliable at either volatility extreme (a trend-strength
    # reading during a volatility spike or a near-dead market is not a
    # meaningful trend/range signal either way).
    if atr_ratio >= config.high_volatility_atr_ratio:
        return MarketRegime.HIGH_VOLATILITY
    if atr_ratio <= config.low_volatility_atr_ratio:
        return MarketRegime.LOW_VOLATILITY
    if trend_ratio >= config.trend_strength_atr_multiple:
        return MarketRegime.TRENDING
    if trend_ratio <= config.range_strength_atr_multiple:
        return MarketRegime.RANGING
    return MarketRegime.UNCERTAIN


def classify_regime(candles: list[Candle], config: RegimeClassifierConfig) -> MarketRegime | None:
    """Classifies the market as of the LAST candle in `candles`. Callers
    control lookahead safety by only ever passing candles up to and
    including "now" (the same convention every Phase 4 candidate's
    `evaluate_*` orchestrator and `analysis/candidate_walk.py` already
    use) -- this function itself never looks beyond the given list.

    Returns None if there isn't enough history yet to classify (mirrors
    the None-for-insufficient-history convention of `ema()`/`atr()`),
    distinct from UNCERTAIN (a genuine, classifiable-but-ambiguous
    reading once there IS enough history).
    """
    if not candles:
        return None
    closes = [c.close for c in candles]
    ema_fast_vals = compute_ema(closes, config.ema_fast_period)
    ema_slow_vals = compute_ema(closes, config.ema_slow_period)
    atr_vals = compute_atr(candles, config.atr_period)
    return _classify_at_index(
        len(candles) - 1,
        ema_fast_vals=ema_fast_vals,
        ema_slow_vals=ema_slow_vals,
        atr_vals=atr_vals,
        config=config,
    )


def classify_regime_series(
    candles: list[Candle], config: RegimeClassifierConfig
) -> list[MarketRegime | None]:
    """Classifies every index in `candles` in one pass (indicators
    computed once, not recomputed per index) -- for diagnostic/backtest
    use, e.g. tagging each historical candle with its regime. Index i's
    classification only ever depends on `candles[:i+1]`, so this is
    equivalent to (but far cheaper than) calling `classify_regime`
    separately on every prefix.
    """
    if not candles:
        return []
    closes = [c.close for c in candles]
    ema_fast_vals = compute_ema(closes, config.ema_fast_period)
    ema_slow_vals = compute_ema(closes, config.ema_slow_period)
    atr_vals = compute_atr(candles, config.atr_period)
    return [
        _classify_at_index(
            i,
            ema_fast_vals=ema_fast_vals,
            ema_slow_vals=ema_slow_vals,
            atr_vals=atr_vals,
            config=config,
        )
        for i in range(len(candles))
    ]
