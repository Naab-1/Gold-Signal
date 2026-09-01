from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.indicators.structure import breakout_and_retest, recent_swing_levels
from goldsignal.models.candle import Candle

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, h, low, c=None, o=None):
    c = c if c is not None else (h + low) / 2
    o = o if o is not None else c
    return Candle(timestamp=START + timedelta(hours=i), open=o, high=h, low=low, close=c, volume=1)


def test_recent_swing_levels_excludes_last_candle_by_default():
    candles = [
        _candle(0, 100, 95),
        _candle(1, 105, 97),
        _candle(2, 102, 94),
        _candle(3, 98, 90),
        _candle(4, 200, 5),  # last candle, excluded by default
    ]
    resistance, support = recent_swing_levels(candles, lookback=3)
    assert resistance == 105  # max high of indices 1..3
    assert support == 90  # min low of indices 1..3


def test_recent_swing_levels_insufficient_history_returns_none():
    candles = [_candle(0, 100, 95), _candle(1, 105, 97)]
    resistance, support = recent_swing_levels(candles, lookback=5)
    assert resistance is None
    assert support is None


def test_breakout_and_retest_bullish_confirmed():
    candles = [
        _candle(0, 101, 99, c=100),  # below level
        _candle(1, 111, 99, c=110),  # breakout close > 105
        _candle(2, 106, 104, c=106),  # retest: low touches near level, holds above
    ]
    assert breakout_and_retest(candles, level=105, bullish=True, tolerance=1.0, confirm_window=3)


def test_breakout_and_retest_bullish_not_confirmed_without_breakout():
    candles = [
        _candle(0, 101, 99, c=100),
        _candle(1, 103, 99, c=102),
        _candle(2, 104, 100, c=103),
    ]
    assert not breakout_and_retest(
        candles, level=105, bullish=True, tolerance=1.0, confirm_window=3
    )


def test_breakout_and_retest_bearish_confirmed():
    candles = [
        _candle(0, 101, 99, c=100),
        _candle(1, 101, 89, c=90),  # breakdown close < 95
        _candle(2, 96, 94, c=94),  # retest from below, holds below
    ]
    assert breakout_and_retest(candles, level=95, bullish=False, tolerance=1.0, confirm_window=3)


def test_breakout_and_retest_requires_hold():
    # breakout happens, but retest candle closes back above the level (fails to hold below)
    candles = [
        _candle(0, 101, 99, c=100),
        _candle(1, 101, 89, c=90),
        _candle(2, 97, 94, c=96),  # touches near level but closes above it
    ]
    assert not breakout_and_retest(
        candles, level=95, bullish=False, tolerance=1.0, confirm_window=3
    )


def test_invalid_params_raise():
    candles = [_candle(0, 100, 95)]
    with pytest.raises(ValueError):
        recent_swing_levels(candles, lookback=0)
    with pytest.raises(ValueError):
        breakout_and_retest(candles, 100, bullish=True, tolerance=-1, confirm_window=1)
