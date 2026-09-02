from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.candle import Timeframe

START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(hours=48)


def test_deterministic_given_same_seed():
    p1 = MockDataProvider(seed=42)
    p2 = MockDataProvider(seed=42)
    c1 = p1.get_candles("XAUUSD", Timeframe.H1, START, END)
    c2 = p2.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert c1 == c2


def test_different_seeds_diverge():
    p1 = MockDataProvider(seed=1)
    p2 = MockDataProvider(seed=2)
    c1 = p1.get_candles("XAUUSD", Timeframe.H1, START, END)
    c2 = p2.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert c1 != c2


def test_candles_spaced_by_timeframe_and_utc():
    provider = MockDataProvider(seed=1)
    candles = provider.get_candles("XAUUSD", Timeframe.M5, START, START + timedelta(hours=1))
    assert len(candles) == 13  # inclusive of both start and end (00:00..01:00 every 5m)
    for a, b in zip(candles, candles[1:], strict=False):
        assert b.timestamp - a.timestamp == Timeframe.M5.duration
        assert b.timestamp.tzinfo is not None


def test_ohlc_internally_consistent():
    provider = MockDataProvider(seed=3, volatility=5.0)
    candles = provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    for c in candles:
        assert c.low <= c.open <= c.high
        assert c.low <= c.close <= c.high
        assert c.volume >= 0


def test_end_before_start_raises():
    provider = MockDataProvider(seed=1)
    with pytest.raises(ValueError):
        provider.get_candles("XAUUSD", Timeframe.H1, END, START)


def test_get_quote_is_deterministic_given_same_seed():
    p1 = MockDataProvider(seed=7)
    p2 = MockDataProvider(seed=7)
    q1 = p1.get_quote("EURUSD")
    q2 = p2.get_quote("EURUSD")
    assert q1.bid == q2.bid
    assert q1.ask == q2.ask
    assert q1.mid == q2.mid


def test_get_quote_diverges_across_instruments():
    provider = MockDataProvider(seed=7)
    q_xau = provider.get_quote("XAUUSD")
    q_eur = provider.get_quote("EURUSD")
    assert q_xau.mid != q_eur.mid


def test_get_quote_provider_is_always_literally_mock():
    provider = MockDataProvider(seed=1)
    assert provider.get_quote("XAUUSD").provider == "mock"


def test_get_quote_bid_le_mid_le_ask():
    provider = MockDataProvider(seed=1)
    quote = provider.get_quote("USDJPY")
    assert quote.bid <= quote.mid <= quote.ask
    assert quote.spread == quote.ask - quote.bid
