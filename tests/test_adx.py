from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.indicators.adx import _directional_moves, _wilder_average, adx, minus_di, plus_di
from goldsignal.models.candle import Candle

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, o, h, low, c):
    return Candle(timestamp=START + timedelta(hours=i), open=o, high=h, low=low, close=c, volume=1)


CANDLES = [
    _candle(0, 10, 12, 8, 10),
    _candle(1, 10, 14, 9, 12),  # up=2, down=-1 -> +DM=2, -DM=0
    _candle(2, 12, 13, 7, 8),  # up=-1, down=2 -> +DM=0, -DM=2
    _candle(3, 8, 9, 6, 7),  # up=-4, down=1 -> +DM=0, -DM=1
]


def test_directional_moves_first_candle_has_no_move():
    plus_dm, minus_dm = _directional_moves(CANDLES)
    assert plus_dm[0] == 0.0
    assert minus_dm[0] == 0.0


def test_directional_moves_up_move_sets_plus_dm_only():
    plus_dm, minus_dm = _directional_moves(CANDLES)
    assert plus_dm[1] == 2.0
    assert minus_dm[1] == 0.0


def test_directional_moves_down_move_sets_minus_dm_only():
    plus_dm, minus_dm = _directional_moves(CANDLES)
    assert plus_dm[2] == 0.0
    assert minus_dm[2] == 2.0
    assert plus_dm[3] == 0.0
    assert minus_dm[3] == 1.0


def test_wilder_average_seed_and_smoothing():
    result = _wilder_average([4.0, 4.0, 5.0, 3.0], period=2)
    assert result[0] is None
    assert result[1] == pytest.approx(4.0)  # avg(4, 4)
    assert result[2] == pytest.approx(4.5)  # (4.0*1 + 5) / 2
    assert result[3] == pytest.approx(3.75)  # (4.5*1 + 3) / 2


def test_adx_rejects_non_positive_period():
    with pytest.raises(ValueError):
        adx(CANDLES, period=0)
    with pytest.raises(ValueError):
        plus_di(CANDLES, period=0)
    with pytest.raises(ValueError):
        minus_di(CANDLES, period=0)


def test_adx_insufficient_candles_returns_all_none():
    assert adx(CANDLES[:2], period=14) == [None, None]


def test_adx_reads_high_for_a_clean_uptrend():
    # Consistently higher highs and higher lows every candle -- a textbook
    # strong trend, which ADX (a well-established, independently-derived
    # benchmark) should read as very high directional movement.
    trend_candles = [_candle(i, 100 + i, 102 + i, 99 + i, 101 + i) for i in range(40)]
    result = adx(trend_candles, period=14)
    assert result[-1] is not None
    assert result[-1] > 90.0


def test_adx_reads_low_for_a_choppy_non_trending_series():
    # Oscillates around the same level every candle -- no net directional
    # movement, which ADX should read as very low.
    range_candles = []
    for i in range(40):
        base = 100 + (2 if i % 2 == 0 else -2)
        range_candles.append(_candle(i, base, base + 1, base - 1, base + 0.2))
    result = adx(range_candles, period=14)
    assert result[-1] is not None
    assert result[-1] < 20.0


def test_plus_di_dominates_in_an_uptrend_minus_di_in_a_downtrend():
    up_candles = [_candle(i, 100 + i, 102 + i, 99 + i, 101 + i) for i in range(30)]
    down_candles = [_candle(i, 200 - i, 202 - i, 199 - i, 201 - i) for i in range(30)]
    assert plus_di(up_candles, 14)[-1] > minus_di(up_candles, 14)[-1]
    assert minus_di(down_candles, 14)[-1] > plus_di(down_candles, 14)[-1]
