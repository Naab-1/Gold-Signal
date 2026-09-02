from datetime import UTC, datetime

from goldsignal.config import load_scalp_config
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection
from goldsignal.strategy.continuation import classify_breakout_candle, classify_confirmation_candle

TS = datetime(2026, 1, 1, tzinfo=UTC)
CONFIG = load_scalp_config(
    {}
)  # defaults: min_atr=0.10, body>=0.60, close_pos<=0.25, max_range<=2.0


def _candle(o, h, low, c):
    return Candle(timestamp=TS, open=o, high=h, low=low, close=c, volume=1)


def test_buy_breakout_candle_qualifies():
    # level=100, ATR=2 -> needs close >= 100 + 0.10*2 = 100.2
    # range=3 (<=2*ATR=4 ok), body=|103-100|/3=1.0>=0.6, close at high (position=1.0>=0.75)
    c = _candle(o=100, h=103, low=100, c=103)
    assert classify_breakout_candle(
        c, level=100, direction=SignalDirection.BUY, atr=2, config=CONFIG
    )


def test_buy_breakout_fails_not_beyond_min_atr_multiple():
    c = _candle(o=100, h=100.15, low=99.9, c=100.1)  # only 0.1 beyond level, needs 0.2
    assert not classify_breakout_candle(
        c, level=100, direction=SignalDirection.BUY, atr=2, config=CONFIG
    )


def test_buy_breakout_fails_small_body():
    # range=3, body=0.5 -> ratio=0.167 < 0.60
    c = _candle(o=101.5, h=103, low=100, c=102.0)
    assert not classify_breakout_candle(
        c, level=100, direction=SignalDirection.BUY, atr=2, config=CONFIG
    )


def test_buy_breakout_fails_close_not_near_high():
    # range=3, close at low end: position = (100.5-100)/3=0.167, need >=0.75
    c = _candle(o=103, h=103, low=100, c=100.5)
    assert not classify_breakout_candle(
        c, level=100, direction=SignalDirection.BUY, atr=2, config=CONFIG
    )


def test_buy_breakout_fails_range_too_large():
    # ATR=2, max_range=2*2=4; range here = 5 (too large), even though other conditions ok
    c = _candle(o=100, h=105, low=100, c=105)
    assert not classify_breakout_candle(
        c, level=100, direction=SignalDirection.BUY, atr=2, config=CONFIG
    )


def test_sell_breakout_candle_qualifies():
    # level=100 (support), close below by >=0.2; close near low
    c = _candle(o=100, h=100, low=97, c=97)
    assert classify_breakout_candle(
        c, level=100, direction=SignalDirection.SELL, atr=2, config=CONFIG
    )


def test_zero_atr_never_qualifies():
    c = _candle(o=100, h=103, low=100, c=103)
    assert not classify_breakout_candle(
        c, level=100, direction=SignalDirection.BUY, atr=0, config=CONFIG
    )


def test_buy_confirmation_candle_confirms():
    c = _candle(
        o=103.5, h=105, low=103, c=104.5
    )  # closes above level(100) and breakout close(103), bullish
    assert classify_confirmation_candle(
        c, level=100, breakout_close=103, direction=SignalDirection.BUY, tolerance=0.5
    )


def test_buy_confirmation_fails_if_not_beyond_breakout_close():
    c = _candle(o=103, h=103.2, low=102, c=102.8)  # below breakout_close=103
    assert not classify_confirmation_candle(
        c, level=100, breakout_close=103, direction=SignalDirection.BUY, tolerance=0.5
    )


def test_buy_confirmation_fails_if_wick_breaches_tolerance():
    c = _candle(o=104, h=105, low=99.3, c=104.5)  # low breaches level(100)-tolerance(0.5)=99.5
    assert not classify_confirmation_candle(
        c, level=100, breakout_close=103, direction=SignalDirection.BUY, tolerance=0.5
    )


def test_buy_confirmation_fails_if_bearish_close():
    c = _candle(
        o=105, h=105, low=103, c=104
    )  # closes above breakout close but bearish (close<open)
    assert not classify_confirmation_candle(
        c, level=100, breakout_close=103, direction=SignalDirection.BUY, tolerance=0.5
    )


def test_sell_confirmation_candle_confirms():
    c = _candle(o=96.5, h=97, low=95, c=95.5)  # below level(100) and breakout_close(97), bearish
    assert classify_confirmation_candle(
        c, level=100, breakout_close=97, direction=SignalDirection.SELL, tolerance=0.5
    )
