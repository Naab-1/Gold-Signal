"""Benchmark comparison for `analysis/regime.py`'s market-regime
classifier (STRATEGY RESEARCH AND REPLACEMENT program, Phase 5) -- see
docs/phase5_market_regime_classification.md for the full write-up and
results.

The classifier itself is built entirely from EMA separation (trend) and
ATR-relative-to-its-own-history (volatility) -- the same building blocks
every Phase 4 candidate family already uses. To check that this isn't
just internally self-consistent but actually agrees with how the
market's condition is conventionally read, this module compares its
calls against two independent, well-established, differently-derived
indicators that were never used to build the classifier itself:

- Trend vs. range: ADX (`indicators/adx.py`), read with the standard
  industry convention (ADX >= 25 => trending, ADX <= 20 => ranging,
  the 20-25 band counted as its own "no clear trend" reading).
- High vs. low volatility: Bollinger Band width (`indicators/bollinger.py`),
  itself compared to its own recent history the same way the
  classifier compares ATR to ATR's recent history -- but derived from
  close-price standard deviation rather than true range, a genuinely
  different statistical basis.

Agreement is measured only over the subset of candles where BOTH
methods make a non-ambiguous call on that axis (e.g. both call
trend/range, or both call high/low volatility) -- comparing against a
method's own "no clear signal" reading would not be a meaningful
agreement check.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass

from goldsignal.analysis.regime import MarketRegime, RegimeClassifierConfig, classify_regime_series
from goldsignal.indicators.adx import adx as compute_adx
from goldsignal.indicators.bollinger import bollinger_band_width
from goldsignal.models.candle import Candle


@dataclass(frozen=True)
class RegimeBenchmarkConfig:
    adx_period: int = 14
    adx_trend_threshold: float = 25.0
    adx_range_threshold: float = 20.0
    bb_period: int = 20
    bb_num_std: float = 2.0
    volatility_lookback: int = 100
    high_volatility_width_ratio: float = 1.4
    low_volatility_width_ratio: float = 0.7


class RegimeBenchmarkReport:
    def __init__(
        self,
        *,
        regime_counts: dict[str, int],
        trend_range_agreement: float | None,
        trend_range_compared_count: int,
        volatility_agreement: float | None,
        volatility_compared_count: int,
    ) -> None:
        self.regime_counts = regime_counts
        self.trend_range_agreement = trend_range_agreement
        self.trend_range_compared_count = trend_range_compared_count
        self.volatility_agreement = volatility_agreement
        self.volatility_compared_count = volatility_compared_count


def _adx_trend_range_label(value: float, config: RegimeBenchmarkConfig) -> str | None:
    if value >= config.adx_trend_threshold:
        return "TRENDING"
    if value <= config.adx_range_threshold:
        return "RANGING"
    return None


def _bb_volatility_label(
    width_vals: list[float | None], idx: int, config: RegimeBenchmarkConfig
) -> str | None:
    current = width_vals[idx]
    if current is None:
        return None
    baseline_start = max(0, idx + 1 - config.volatility_lookback)
    window = [v for v in width_vals[baseline_start : idx + 1] if v is not None]
    if len(window) < config.volatility_lookback:
        return None
    baseline = statistics.median(window)
    if baseline <= 0:
        return None
    ratio = current / baseline
    if ratio >= config.high_volatility_width_ratio:
        return "HIGH_VOLATILITY"
    if ratio <= config.low_volatility_width_ratio:
        return "LOW_VOLATILITY"
    return None


def compare_regime_to_benchmark(
    candles: list[Candle],
    regime_config: RegimeClassifierConfig,
    benchmark_config: RegimeBenchmarkConfig | None = None,
) -> RegimeBenchmarkReport:
    benchmark_config = benchmark_config or RegimeBenchmarkConfig()
    classified = classify_regime_series(candles, regime_config)
    regime_counts: Counter[str] = Counter(r.value for r in classified if r is not None)

    adx_vals = compute_adx(candles, benchmark_config.adx_period)
    closes = [c.close for c in candles]
    width_vals = bollinger_band_width(
        closes, benchmark_config.bb_period, benchmark_config.bb_num_std
    )

    trend_range_total = 0
    trend_range_agree = 0
    volatility_total = 0
    volatility_agree = 0

    for i, regime in enumerate(classified):
        if regime is None:
            continue

        adx_value = adx_vals[i]
        if adx_value is not None and regime in (MarketRegime.TRENDING, MarketRegime.RANGING):
            benchmark_label = _adx_trend_range_label(adx_value, benchmark_config)
            if benchmark_label is not None:
                trend_range_total += 1
                if benchmark_label == regime.value:
                    trend_range_agree += 1

        if regime in (MarketRegime.HIGH_VOLATILITY, MarketRegime.LOW_VOLATILITY):
            benchmark_label = _bb_volatility_label(width_vals, i, benchmark_config)
            if benchmark_label is not None:
                volatility_total += 1
                if benchmark_label == regime.value:
                    volatility_agree += 1

    return RegimeBenchmarkReport(
        regime_counts=dict(regime_counts),
        trend_range_agreement=(trend_range_agree / trend_range_total)
        if trend_range_total
        else None,
        trend_range_compared_count=trend_range_total,
        volatility_agreement=(volatility_agree / volatility_total) if volatility_total else None,
        volatility_compared_count=volatility_total,
    )
