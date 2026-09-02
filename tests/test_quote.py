from datetime import UTC, datetime

import pytest

from goldsignal.models.quote import PriceSource, Quote

UTC_TS = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
NAIVE_TS = datetime(2026, 1, 15, 12, 0)


def _quote(**overrides):
    fields = {
        "instrument": "XAUUSD",
        "provider": "twelvedata",
        "quote_timestamp": UTC_TS,
        "last_price": 2450.0,
        "price_source": PriceSource.LAST_TRADE_PRICE,
    }
    fields.update(overrides)
    return Quote(**fields)


def test_valid_quote_without_bid_ask():
    q = _quote()
    assert q.bid is None
    assert q.spread is None


def test_valid_quote_with_bid_ask_mid_spread():
    q = _quote(price_source=PriceSource.BID_ASK_MID, bid=2449.9, ask=2450.1, mid=2450.0, spread=0.2)
    assert q.mid == 2450.0
    assert q.spread == 0.2


def test_bid_without_ask_raises():
    with pytest.raises(ValueError):
        _quote(bid=2449.9)


def test_ask_without_bid_raises():
    with pytest.raises(ValueError):
        _quote(ask=2450.1)


def test_bid_ask_present_but_mid_missing_raises():
    with pytest.raises(ValueError):
        _quote(bid=2449.9, ask=2450.1, spread=0.2)


def test_bid_ask_present_but_spread_missing_raises():
    with pytest.raises(ValueError):
        _quote(bid=2449.9, ask=2450.1, mid=2450.0)


def test_naive_timestamp_raises():
    with pytest.raises(ValueError):
        _quote(quote_timestamp=NAIVE_TS)
