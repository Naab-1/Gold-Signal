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
