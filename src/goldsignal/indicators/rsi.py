"""Relative Strength Index, Wilder's smoothing method."""

from __future__ import annotations

from collections.abc import Sequence


def rsi(closes: Sequence[float], period: int) -> list[float | None]:
    """RSI(period) over `closes`.

    Needs `period` price changes (i.e. `period + 1` closes) before the
    first value; earlier indices are None. Uses Wilder's smoothing for the
    average gain/loss, seeded with a simple average of the first `period`
    changes.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(closes)
    result: list[float | None] = [None] * n
    if n < period + 1:
        return result

    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        change = closes[i] - closes[i - 1]
        gains[i] = max(change, 0.0)
        losses[i] = max(-change, 0.0)

    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        result[i] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
