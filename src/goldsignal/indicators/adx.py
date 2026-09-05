"""Average Directional Index (ADX), +DI/-DI, Wilder's method.

Built for Phase 5 (STRATEGY RESEARCH AND REPLACEMENT program --
market-regime classification) as an independent, well-established
benchmark for trend/range strength -- `analysis/regime.py`'s own
classifier uses EMA-separation-relative-to-ATR (the same approach every
Phase 4 candidate family already uses), and ADX is a completely
different, industry-standard derivation (directional movement smoothed
against true range) used only to check the two methods agree, not to
feed the classifier itself.
"""

from __future__ import annotations

from collections.abc import Sequence

from goldsignal.indicators.atr import true_range
from goldsignal.models.candle import Candle


def _directional_moves(candles: Sequence[Candle]) -> tuple[list[float], list[float]]:
    """+DM/-DM per candle. Index 0 has no prior candle to compare against,
    so it carries no directional move (0.0) -- the same "use what's
    available, default to the neutral case" convention `true_range`
    already uses at its own index 0.
    """
    n = len(candles)
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up_move = candles[i].high - candles[i - 1].high
        down_move = candles[i - 1].low - candles[i].low
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
    return plus_dm, minus_dm


def _wilder_average(values: Sequence[float], period: int) -> list[float | None]:
    """Wilder's smoothed average: seeded as the simple average of the
    first `period` values, then recursively smoothed. Structurally
    identical to `atr.py::atr`'s own smoothing of true range -- kept as
    its own private copy here (rather than extracted into a shared,
    exported helper) so this new indicator never risks a behavioral
    change to the already-verified `atr()` function every strategy in
    this project depends on.
    """
    n = len(values)
    result: list[float | None] = [None] * n
    if n < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    prev = seed
    for i in range(period, n):
        prev = (prev * (period - 1) + values[i]) / period
        result[i] = prev
    return result


def plus_di(candles: Sequence[Candle], period: int) -> list[float | None]:
    """+DI(period): Wilder-smoothed +DM as a percentage of Wilder-smoothed
    true range.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    plus_dm, _minus_dm = _directional_moves(candles)
    smoothed_dm = _wilder_average(plus_dm, period)
    smoothed_tr = _wilder_average(true_range(candles), period)
    return [
        (100.0 * dm / tr) if (dm is not None and tr is not None and tr != 0) else None
        for dm, tr in zip(smoothed_dm, smoothed_tr, strict=True)
    ]


def minus_di(candles: Sequence[Candle], period: int) -> list[float | None]:
    """-DI(period): Wilder-smoothed -DM as a percentage of Wilder-smoothed
    true range.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    _plus_dm, minus_dm = _directional_moves(candles)
    smoothed_dm = _wilder_average(minus_dm, period)
    smoothed_tr = _wilder_average(true_range(candles), period)
    return [
        (100.0 * dm / tr) if (dm is not None and tr is not None and tr != 0) else None
        for dm, tr in zip(smoothed_dm, smoothed_tr, strict=True)
    ]


def adx(candles: Sequence[Candle], period: int) -> list[float | None]:
    """ADX(period): Wilder-smoothed average of DX = 100 * |+DI - -DI| /
    (+DI + -DI). Needs roughly 2*period candles before the first value
    (period candles to seed +DI/-DI, then another period DX values to
    seed ADX itself) -- earlier indices are None.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    n = len(candles)
    plus_dm, minus_dm = _directional_moves(candles)
    smoothed_plus_dm = _wilder_average(plus_dm, period)
    smoothed_minus_dm = _wilder_average(minus_dm, period)
    smoothed_tr = _wilder_average(true_range(candles), period)

    dx: list[float | None] = [None] * n
    for i in range(n):
        p, m, tr = smoothed_plus_dm[i], smoothed_minus_dm[i], smoothed_tr[i]
        if p is None or m is None or tr is None or tr == 0:
            continue
        p_di = 100.0 * p / tr
        m_di = 100.0 * m / tr
        total = p_di + m_di
        dx[i] = (100.0 * abs(p_di - m_di) / total) if total != 0 else 0.0

    first_dx_idx = next((i for i, v in enumerate(dx) if v is not None), None)
    result: list[float | None] = [None] * n
    if first_dx_idx is None:
        return result
    dx_values = [v for v in dx[first_dx_idx:] if v is not None]
    smoothed_dx = _wilder_average(dx_values, period)
    for offset, value in enumerate(smoothed_dx):
        if value is not None:
            result[first_dx_idx + offset] = value
    return result
