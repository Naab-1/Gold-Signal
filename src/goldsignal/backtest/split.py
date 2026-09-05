"""Chronological development / out-of-sample split.

Splitting the *candle series* itself (rather than trades by timestamp)
would throw away indicator warmup history for the out-of-sample segment,
so instead: run signal generation once over the full series, then split
the resulting trades by whether their signal falls before or after a
cutoff timestamp computed from the candle series.
"""

from __future__ import annotations

from datetime import datetime

from goldsignal.backtest.models import BacktestTrade
from goldsignal.models.candle import Candle

DEFAULT_SPLIT_RATIO = 0.7


def split_cutoff_timestamp(
    candles: list[Candle], split_ratio: float = DEFAULT_SPLIT_RATIO
) -> datetime:
    if not 0 < split_ratio < 1:
        raise ValueError("split_ratio must be between 0 and 1 (exclusive)")
    if not candles:
        raise ValueError("candles must not be empty")
    idx = min(max(int(len(candles) * split_ratio), 0), len(candles) - 1)
    return candles[idx].timestamp


def split_trades(
    trades: list[BacktestTrade], cutoff: datetime
) -> tuple[list[BacktestTrade], list[BacktestTrade]]:
    development = [t for t in trades if t.signal_timestamp < cutoff]
    out_of_sample = [t for t in trades if t.signal_timestamp >= cutoff]
    return development, out_of_sample


# Three-way development/validation/final-out-of-sample split, for the
# STRATEGY RESEARCH AND REPLACEMENT program's Phase 3 (chronological data
# separation). 70/15/15 rather than an even 50/25/25: this project's real
# trade counts (docs/baseline_rejection.md) show even the existing 70/30
# two-way split leaves some instruments with single-digit out-of-sample
# trades (EUR/USD: 5, GBP/USD: 4) -- a further, even split would shrink
# that final slice to ~2-3 trades, not a verdict. 70/15/15 preserves the
# existing dev/oos boundary (just carving validation out of the old 30%)
# without shrinking development, which candidate-strategy design needs
# most. See docs/phase3_data_separation.md.
DEFAULT_DEV_RATIO = 0.7
DEFAULT_VALIDATION_RATIO = 0.15  # implied final-oos ratio = 1 - dev_ratio - validation_ratio


def split_cutoff_timestamps(
    candles: list[Candle],
    dev_ratio: float = DEFAULT_DEV_RATIO,
    validation_ratio: float = DEFAULT_VALIDATION_RATIO,
) -> tuple[datetime, datetime]:
    """Two cutoffs partitioning `candles` into development / validation /
    final-out-of-sample. Reuses `split_cutoff_timestamp` twice (single
    source of truth for the index math) rather than reimplementing it.
    """
    if not 0 < dev_ratio:
        raise ValueError("dev_ratio must be greater than 0")
    if not 0 < validation_ratio:
        raise ValueError("validation_ratio must be greater than 0")
    if dev_ratio + validation_ratio >= 1:
        raise ValueError(
            "dev_ratio + validation_ratio must be less than 1 "
            "(a non-empty final out-of-sample slice must remain)"
        )
    cutoff1 = split_cutoff_timestamp(candles, dev_ratio)
    cutoff2 = split_cutoff_timestamp(candles, dev_ratio + validation_ratio)
    return cutoff1, cutoff2


def split_trades_three_way(
    trades: list[BacktestTrade], cutoff1: datetime, cutoff2: datetime
) -> tuple[list[BacktestTrade], list[BacktestTrade], list[BacktestTrade]]:
    development = [t for t in trades if t.signal_timestamp < cutoff1]
    validation = [t for t in trades if cutoff1 <= t.signal_timestamp < cutoff2]
    final_out_of_sample = [t for t in trades if t.signal_timestamp >= cutoff2]
    return development, validation, final_out_of_sample
