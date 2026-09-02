"""Two-Candle Breakout Continuation rule (the "A" tier) — a precisely
specified, objectively testable alternative to A+'s breakout/retest,
experimental until independently backtested. Pure, closed-candle-only
predicates; no lookahead — the breakout candle's qualifying level must
already be defined from candles before it (reuses
`indicators/structure.recent_swing_levels`, unchanged).
"""

from __future__ import annotations

from goldsignal.config import ModeConfig
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection


def classify_breakout_candle(
    candle: Candle,
    *,
    level: float,
    direction: SignalDirection,
    atr: float,
    config: ModeConfig,
) -> bool:
    """True if `candle` qualifies as the first (breakout) candle of the
    Two-Candle Continuation pattern against `level` (resistance for BUY,
    support for SELL).
    """
    if atr <= 0:
        return False
    is_buy = direction == SignalDirection.BUY

    beyond = (candle.close - level) if is_buy else (level - candle.close)
    if beyond < config.continuation_breakout_min_atr_multiple * atr:
        return False

    full_range = candle.high - candle.low
    if full_range <= 0:
        return False

    body = abs(candle.close - candle.open)
    if body / full_range < config.continuation_min_body_ratio:
        return False

    close_position = (candle.close - candle.low) / full_range  # 0 = at low, 1 = at high
    if is_buy:
        if close_position < (1 - config.continuation_close_position_ratio):
            return False
    else:
        if close_position > config.continuation_close_position_ratio:
            return False

    if full_range > config.continuation_max_range_atr_multiple * atr:
        return False

    return True


def classify_confirmation_candle(
    candle: Candle,
    *,
    level: float,
    breakout_close: float,
    direction: SignalDirection,
    tolerance: float,
) -> bool:
    """True if `candle` (the very next completed candle after the
    breakout candle) confirms continuation.
    """
    is_buy = direction == SignalDirection.BUY
    if is_buy:
        if candle.close <= level:
            return False
        if candle.close <= breakout_close:
            return False
        if candle.low < level - tolerance:
            return False
        return candle.close > candle.open  # bullish close
    else:
        if candle.close >= level:
            return False
        if candle.close >= breakout_close:
            return False
        if candle.high > level + tolerance:
            return False
        return candle.close < candle.open  # bearish close
