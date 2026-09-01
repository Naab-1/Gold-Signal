from datetime import UTC, datetime, timedelta, timezone

import pytest

from goldsignal.models.candle import Candle, Timeframe


def test_candle_requires_utc_timestamp():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError):
        Candle(timestamp=naive, open=1, high=2, low=0.5, close=1.5, volume=10)


def test_candle_rejects_non_utc_offset():
    other_tz = timezone(timedelta(hours=1))
    dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=other_tz)
    with pytest.raises(ValueError):
        Candle(timestamp=dt, open=1, high=2, low=0.5, close=1.5, volume=10)


def test_candle_accepts_utc_timestamp():
    dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    c = Candle(timestamp=dt, open=1, high=2, low=0.5, close=1.5, volume=10)
    assert c.timestamp == dt


def test_timeframe_durations():
    assert Timeframe.M5.duration == timedelta(minutes=5)
    assert Timeframe.M15.duration == timedelta(minutes=15)
    assert Timeframe.H1.duration == timedelta(hours=1)
