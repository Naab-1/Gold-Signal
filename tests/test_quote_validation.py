import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.data.quote_validation import assess_quote, is_quote_stale
from goldsignal.instruments import load_instrument_profile
from goldsignal.models.quote import PriceSource, Quote

TS = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def _quote(**overrides):
    fields = {
        "instrument": "EURUSD",
        "provider": "twelvedata",
        "quote_timestamp": TS,
        "last_price": 1.0850,
        "price_source": PriceSource.LAST_TRADE_PRICE,
    }
    fields.update(overrides)
    return Quote(**fields)


def _profile(**overrides):
    profile = load_instrument_profile("EURUSD", {})
    if overrides:
        profile = dataclasses.replace(profile, **overrides)
    return profile


def test_is_quote_stale_false_when_within_max_age():
    q = _quote(quote_timestamp=TS)
    assert is_quote_stale(q, TS + timedelta(seconds=30), timedelta(seconds=60)) is False


def test_is_quote_stale_true_when_beyond_max_age():
    q = _quote(quote_timestamp=TS)
    assert is_quote_stale(q, TS + timedelta(seconds=90), timedelta(seconds=60)) is True


def test_is_quote_stale_boundary_is_not_stale():
    q = _quote(quote_timestamp=TS)
    assert is_quote_stale(q, TS + timedelta(seconds=60), timedelta(seconds=60)) is False


def test_assess_quote_fresh_no_spread_no_broker():
    profile = _profile()
    q = _quote(quote_timestamp=TS)
    result = assess_quote(q, profile, TS, max_quote_age=timedelta(minutes=2))
    assert result.is_stale is False
    assert result.spread_exceeds_max is None  # spread not supplied
    assert result.broker_mismatch is None


def test_assess_quote_spread_within_limit():
    profile = _profile(max_permitted_spread=0.0005)
    q = _quote(
        quote_timestamp=TS,
        price_source=PriceSource.BID_ASK_MID,
        bid=1.08495,
        ask=1.08505,
        mid=1.0850,
        spread=0.0001,
    )
    result = assess_quote(q, profile, TS, max_quote_age=timedelta(minutes=2))
    assert result.spread_exceeds_max is False


def test_assess_quote_spread_exceeds_limit():
    profile = _profile(max_permitted_spread=0.00005)
    q = _quote(
        quote_timestamp=TS,
        price_source=PriceSource.BID_ASK_MID,
        bid=1.08495,
        ask=1.08505,
        mid=1.0850,
        spread=0.0001,
    )
    result = assess_quote(q, profile, TS, max_quote_age=timedelta(minutes=2))
    assert result.spread_exceeds_max is True


def test_assess_quote_broker_price_matches_within_tolerance():
    profile = _profile(broker_price_tolerance=0.0005)
    q = _quote(quote_timestamp=TS, last_price=1.0850)
    result = assess_quote(q, profile, TS, max_quote_age=timedelta(minutes=2), broker_price=1.0852)
    assert result.broker_mismatch is False
    assert result.broker_diff == pytest.approx(0.0002)


def test_assess_quote_broker_price_mismatch_beyond_tolerance():
    profile = _profile(broker_price_tolerance=0.0005)
    q = _quote(quote_timestamp=TS, last_price=1.0850)
    result = assess_quote(q, profile, TS, max_quote_age=timedelta(minutes=2), broker_price=1.0900)
    assert result.broker_mismatch is True


def test_assess_quote_broker_tolerance_override_wins_over_profile_default():
    profile = _profile(broker_price_tolerance=0.0005)
    q = _quote(quote_timestamp=TS, last_price=1.0850)
    # Would mismatch under the profile's own tolerance, but the explicit
    # override widens it enough to match.
    result = assess_quote(
        q,
        profile,
        TS,
        max_quote_age=timedelta(minutes=2),
        broker_price=1.0900,
        broker_tolerance=0.01,
    )
    assert result.broker_mismatch is False


def test_assess_quote_uses_mid_over_last_price_for_broker_comparison_when_available():
    profile = _profile(broker_price_tolerance=0.00001)
    q = _quote(
        quote_timestamp=TS,
        last_price=1.0850,
        price_source=PriceSource.BID_ASK_MID,
        bid=1.0899,
        ask=1.0901,
        mid=1.0900,
        spread=0.0002,
    )
    result = assess_quote(q, profile, TS, max_quote_age=timedelta(minutes=2), broker_price=1.0900)
    assert result.broker_mismatch is False  # compared against mid (1.0900), not last_price
