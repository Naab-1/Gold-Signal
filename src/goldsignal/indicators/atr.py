"""Average True Range, Wilder's smoothing method."""

from __future__ import annotations

from collections.abc import Sequence

from goldsignal.models.candle import Candle


def true_range(candles: Sequence[Candle]) -> list[float]:
    """True range per candle. The first candle has no prior close, so its
    true range is simply high - low.
    """
    tr: list[float] = []
    prev_close: float | None = None
    for c in candles:
        if prev_close is None:
            tr.append(c.high - c.low)
        else:
            tr.append(max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close)))
        prev_close = c.close
    return tr


def atr(candles: Sequence[Candle], period: int) -> list[float | None]:
    """ATR(period) over `candles`. First value seeded as the simple average
    of the first `period` true-range values (index `period - 1`), then
    smoothed with Wilder's method. Earlier indices are None.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(candles)
    result: list[float | None] = [None] * n
    if n < period:
        return result

    tr = true_range(candles)
    seed = sum(tr[:period]) / period
    result[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = (prev * (period - 1) + tr[i]) / period
        result[i] = prev
    return result
