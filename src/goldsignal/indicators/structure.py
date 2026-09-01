"""Market structure helpers: recent swing support/resistance and
breakout-and-retest confirmation, used by the strategy's confirmation
checklist.
"""

from __future__ import annotations

from collections.abc import Sequence

from goldsignal.models.candle import Candle


def recent_swing_levels(
    candles: Sequence[Candle],
    lookback: int,
    *,
    exclude_last: int = 1,
) -> tuple[float | None, float | None]:
    """Resistance/support as the max high / min low over `lookback` candles
    preceding the most recent `exclude_last` candle(s) (the candle a signal
    is being evaluated on is excluded by default, so the level isn't
    computed using the very bar it's meant to confirm).

    Returns (None, None) if there isn't enough history.
    """
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    if exclude_last < 0:
        raise ValueError("exclude_last must not be negative")

    usable = candles[: len(candles) - exclude_last] if exclude_last else candles
    window = usable[-lookback:]
    if len(window) < lookback:
        return None, None
    resistance = max(c.high for c in window)
    support = min(c.low for c in window)
    return resistance, support


def breakout_and_retest(
    candles: Sequence[Candle],
    level: float,
    *,
    bullish: bool,
    tolerance: float,
    confirm_window: int,
) -> bool:
    """True if, within the last `confirm_window` candles, price broke out
    beyond `level` and later retested it (came back within `tolerance`)
    while holding on the correct side (not fully reversing back through
    the level).

    `bullish=True` checks a resistance breakout + retest-from-above (BUY
    setup); `bullish=False` checks a support breakdown + retest-from-below
    (SELL setup).
    """
    if confirm_window <= 0:
        raise ValueError("confirm_window must be positive")
    if tolerance < 0:
        raise ValueError("tolerance must not be negative")

    window = list(candles[-confirm_window:])

    breakout_idx: int | None = None
    for i, c in enumerate(window):
        if bullish and c.close > level:
            breakout_idx = i
            break
        if not bullish and c.close < level:
            breakout_idx = i
            break
    if breakout_idx is None:
        return False

    for c in window[breakout_idx + 1 :]:
        if bullish:
            touched_level = c.low <= level + tolerance
            held_above = c.close > level
            if touched_level and held_above:
                return True
        else:
            touched_level = c.high >= level - tolerance
            held_below = c.close < level
            if touched_level and held_below:
                return True
    return False
