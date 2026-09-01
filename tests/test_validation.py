from datetime import UTC, datetime, timedelta

from goldsignal.data.validation import validate_candles
from goldsignal.models.candle import Candle, Timeframe

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(offset_hours, **overrides):
    ts = START + timedelta(hours=offset_hours)
    defaults = dict(timestamp=ts, open=100.0, high=101.0, low=99.0, close=100.5, volume=10.0)
    defaults.update(overrides)
    return Candle(**defaults)


def test_clean_candles_pass_through():
    candles = [_candle(i) for i in range(5)]
    result = validate_candles(candles, Timeframe.H1, now=START + timedelta(hours=4))
    assert result.clean_candles == candles
    assert result.is_usable
    assert result.issues == []


def test_duplicate_timestamp_dropped():
    candles = [_candle(0), _candle(0), _candle(1)]
    result = validate_candles(candles, Timeframe.H1, now=START + timedelta(hours=1))
    assert len(result.clean_candles) == 2
    assert any("duplicate" in issue for issue in result.issues)


def test_out_of_order_dropped():
    candles = [_candle(2), _candle(1), _candle(3)]
    result = validate_candles(candles, Timeframe.H1, now=START + timedelta(hours=3))
    assert [c.timestamp for c in result.clean_candles] == [
        START + timedelta(hours=2),
        START + timedelta(hours=3),
    ]
    assert any("out-of-order" in issue for issue in result.issues)


def test_gap_reported_but_not_dropped():
    candles = [_candle(0), _candle(3)]
    result = validate_candles(candles, Timeframe.H1, now=START + timedelta(hours=3))
    assert len(result.clean_candles) == 2
    assert any("gap detected" in issue for issue in result.issues)


def test_malformed_high_below_low_dropped():
    candles = [_candle(0, high=90.0, low=99.0)]
    result = validate_candles(candles, Timeframe.H1, now=START)
    assert result.clean_candles == []
    assert any("high_below_low" in issue for issue in result.issues)


def test_negative_volume_dropped():
    candles = [_candle(0, volume=-5.0)]
    result = validate_candles(candles, Timeframe.H1, now=START)
    assert result.clean_candles == []


def test_close_outside_high_low_dropped():
    candles = [_candle(0, close=200.0)]
    result = validate_candles(candles, Timeframe.H1, now=START)
    assert result.clean_candles == []


def test_stale_data_flagged():
    candles = [_candle(0)]
    now = START + timedelta(hours=10)
    result = validate_candles(candles, Timeframe.H1, now=now)
    assert result.is_stale
    assert not result.is_usable


def test_empty_input_reports_issue():
    result = validate_candles([], Timeframe.H1, now=START)
    assert result.clean_candles == []
    assert not result.is_usable
    assert result.issues == ["no valid candles after validation"]
