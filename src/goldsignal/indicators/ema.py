"""Exponential moving average."""

from __future__ import annotations

from collections.abc import Sequence


def ema(values: Sequence[float], period: int) -> list[float | None]:
    """Standard EMA: seeded with the SMA of the first `period` values, then
    smoothed with multiplier k = 2 / (period + 1). Indices before the seed
    point are None (insufficient history).
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(values)
    result: list[float | None] = [None] * n
    if n < period:
        return result

    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = values[i] * k + prev * (1 - k)
        result[i] = prev
    return result
