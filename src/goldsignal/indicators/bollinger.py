"""Bollinger Bands and band width.

Built for Phase 5 (STRATEGY RESEARCH AND REPLACEMENT program --
market-regime classification) as an independent, well-established
benchmark for volatility: `analysis/regime.py`'s own classifier reads
volatility from ATR relative to its own recent history, while band
width is derived from close-price standard deviation -- a completely
different statistical basis -- used only to check the two methods
agree, not to feed the classifier itself.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence


def bollinger_bands(
    closes: Sequence[float], period: int, num_std: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """(upper, middle, lower) bands: middle is the simple moving average
    of `closes` over `period`; upper/lower are `num_std` population
    standard deviations above/below it. Earlier indices (insufficient
    history) are None.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    if num_std <= 0:
        raise ValueError("num_std must be positive")
    n = len(closes)
    upper: list[float | None] = [None] * n
    middle: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        mean = sum(window) / period
        std = statistics.pstdev(window)
        middle[i] = mean
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std
    return upper, middle, lower


def bollinger_band_width(
    closes: Sequence[float], period: int, num_std: float = 2.0
) -> list[float | None]:
    """(upper - lower) / middle at each index -- a scale-free measure of
    how wide the bands are relative to price, so it can be compared
    across instruments/price levels the same way ATR-relative-to-price
    can. None wherever the middle band is None or zero.
    """
    upper, middle, lower = bollinger_bands(closes, period, num_std)
    width: list[float | None] = [None] * len(closes)
    for i in range(len(closes)):
        u, m, lo = upper[i], middle[i], lower[i]
        if u is None or m is None or lo is None or m == 0:
            continue
        width[i] = (u - lo) / m
    return width
