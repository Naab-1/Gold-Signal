from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.indicators.atr import atr, true_range
from goldsignal.models.candle import Candle

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, o, h, low, c):
    return Candle(timestamp=START + timedelta(hours=i), open=o, high=h, low=low, close=c, volume=1)


CANDLES = [
    _candle(0, 10, 12, 8, 10),
    _candle(1, 10, 13, 9, 11),
    _candle(2, 11, 15, 10, 14),
    _candle(3, 14, 16, 13, 15),
]


def test_true_range_first_candle_is_high_minus_low():
    tr = true_range(CANDLES)
    assert tr[0] == 4.0  # 12 - 8


def test_true_range_uses_prev_close_when_larger_range():
    tr = true_range(CANDLES)
    assert tr[1] == 4.0  # max(13-9=4, |13-10|=3, |9-10|=1)
    assert tr[2] == 5.0  # max(15-10=5, |15-11|=4, |10-11|=1)
    assert tr[3] == 3.0  # max(16-13=3, |16-14|=2, |13-14|=1)


def test_atr_seed_and_wilder_smoothing():
    result = atr(CANDLES, period=2)
    assert result[0] is None
    assert result[1] == pytest.approx(4.0)  # avg(TR0, TR1) = avg(4, 4)
    assert result[2] == pytest.approx(4.5)  # (4.0*1 + 5) / 2
    assert result[3] == pytest.approx(3.75)  # (4.5*1 + 3) / 2


def test_atr_rejects_non_positive_period():
    with pytest.raises(ValueError):
        atr(CANDLES, period=0)


def test_atr_insufficient_candles_returns_all_none():
    result = atr(CANDLES[:1], period=5)
    assert result == [None]
