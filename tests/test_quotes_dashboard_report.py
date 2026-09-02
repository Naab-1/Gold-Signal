from datetime import UTC, datetime, timedelta

from goldsignal.analysis.report import format_quotes_dashboard
from goldsignal.data.quote_validation import QuoteAssessment
from goldsignal.instruments import load_instrument_profile
from goldsignal.models.quote import PriceSource, Quote

TS = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def test_unavailable_instrument_is_labeled_explicitly():
    profile = load_instrument_profile("USDJPY", {})
    text = format_quotes_dashboard([(profile, None, "network timeout")], now=TS)
    assert "DATA UNAVAILABLE" in text
    assert "network timeout" in text


def test_no_bid_ask_labeled_not_supplied():
    profile = load_instrument_profile("XAUUSD", {})
    quote = Quote(
        instrument="XAUUSD",
        provider="twelvedata",
        quote_timestamp=TS,
        last_price=2450.0,
        price_source=PriceSource.LAST_TRADE_PRICE,
    )
    assessment = QuoteAssessment(
        quote=quote,
        is_stale=False,
        spread_exceeds_max=None,
        broker_price=None,
        broker_diff=None,
        broker_mismatch=None,
    )
    text = format_quotes_dashboard([(profile, assessment, None)], now=TS)
    assert "not supplied by this provider" in text


def test_stale_quote_flagged():
    profile = load_instrument_profile("XAUUSD", {})
    quote = Quote(
        instrument="XAUUSD",
        provider="twelvedata",
        quote_timestamp=TS - timedelta(hours=2),
        last_price=2450.0,
        price_source=PriceSource.LAST_TRADE_PRICE,
    )
    assessment = QuoteAssessment(
        quote=quote,
        is_stale=True,
        spread_exceeds_max=None,
        broker_price=None,
        broker_diff=None,
        broker_mismatch=None,
    )
    text = format_quotes_dashboard([(profile, assessment, None)], now=TS)
    assert "Stale: YES" in text


def test_market_closed_flagged():
    profile = load_instrument_profile("EURUSD", {})
    quote = Quote(
        instrument="EURUSD",
        provider="twelvedata",
        quote_timestamp=TS,
        last_price=1.0850,
        price_source=PriceSource.LAST_TRADE_PRICE,
        market_open=False,
    )
    assessment = QuoteAssessment(
        quote=quote,
        is_stale=False,
        spread_exceeds_max=None,
        broker_price=None,
        broker_diff=None,
        broker_mismatch=None,
    )
    text = format_quotes_dashboard([(profile, assessment, None)], now=TS)
    assert "Market: CLOSED" in text


def test_spread_exceeds_max_flagged():
    profile = load_instrument_profile("EURUSD", {})
    quote = Quote(
        instrument="EURUSD",
        provider="twelvedata",
        quote_timestamp=TS,
        last_price=1.0850,
        price_source=PriceSource.BID_ASK_MID,
        bid=1.084,
        ask=1.086,
        mid=1.085,
        spread=0.002,
    )
    assessment = QuoteAssessment(
        quote=quote,
        is_stale=False,
        spread_exceeds_max=True,
        broker_price=None,
        broker_diff=None,
        broker_mismatch=None,
    )
    text = format_quotes_dashboard([(profile, assessment, None)], now=TS)
    assert "EXCEEDS max" in text


def test_broker_mismatch_flagged():
    profile = load_instrument_profile("XAUUSD", {})
    quote = Quote(
        instrument="XAUUSD",
        provider="twelvedata",
        quote_timestamp=TS,
        last_price=2450.0,
        price_source=PriceSource.LAST_TRADE_PRICE,
    )
    assessment = QuoteAssessment(
        quote=quote,
        is_stale=False,
        spread_exceeds_max=None,
        broker_price=2500.0,
        broker_diff=50.0,
        broker_mismatch=True,
    )
    text = format_quotes_dashboard([(profile, assessment, None)], now=TS)
    assert "MISMATCH" in text


def test_shows_utc_and_accra_time():
    profile = load_instrument_profile("XAUUSD", {})
    quote = Quote(
        instrument="XAUUSD",
        provider="twelvedata",
        quote_timestamp=TS,
        last_price=2450.0,
        price_source=PriceSource.LAST_TRADE_PRICE,
    )
    assessment = QuoteAssessment(
        quote=quote,
        is_stale=False,
        spread_exceeds_max=None,
        broker_price=None,
        broker_diff=None,
        broker_mismatch=None,
    )
    text = format_quotes_dashboard([(profile, assessment, None)], now=TS)
    assert "UTC" in text
    assert "Accra" in text
