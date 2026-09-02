from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from goldsignal.data.twelvedata_provider import DataProviderError, TwelveDataProvider
from goldsignal.models.candle import Timeframe

START = datetime(2024, 1, 15, tzinfo=UTC)
END = datetime(2024, 1, 16, tzinfo=UTC)


def _response(
    status_code=200, body=None, url="https://api.twelvedata.com/time_series?apikey=SECRET123"
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.url = url
    if body is not None:
        resp.json.return_value = body
    return resp


def _session_returning(*responses):
    session = MagicMock()
    session.get.side_effect = list(responses)
    return session


def test_parses_and_converts_exchange_timezone_to_utc():
    # 09:00 in America/New_York (EST, UTC-5 in January) -> 14:00 UTC
    body = {
        "meta": {"symbol": "XAU/USD", "exchange_timezone": "America/New_York"},
        "values": [
            {
                "datetime": "2024-01-15 09:05:00",
                "open": "2010",
                "high": "2012",
                "low": "2009",
                "close": "2011",
                "volume": "0",
            },
            {
                "datetime": "2024-01-15 09:00:00",
                "open": "2005",
                "high": "2011",
                "low": "2004",
                "close": "2010",
                "volume": "0",
            },
        ],
        "status": "ok",
    }
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="SECRET123", session=session, verify_consistency=False)

    candles = provider.get_candles("XAUUSD", Timeframe.M5, START, END)

    assert len(candles) == 2
    assert candles[0].timestamp < candles[1].timestamp  # reordered ascending
    assert candles[0].timestamp == datetime(2024, 1, 15, 14, 0, tzinfo=UTC)
    assert candles[1].timestamp == datetime(2024, 1, 15, 14, 5, tzinfo=UTC)
    assert candles[0].open == 2005.0
    assert candles[0].timestamp.tzinfo is not None


def test_missing_volume_defaults_to_zero():
    body = {
        "meta": {"exchange_timezone": "UTC"},
        "values": [
            {
                "datetime": "2024-01-15 09:00:00",
                "open": "1",
                "high": "2",
                "low": "0.5",
                "close": "1.5",
            }
        ],
        "status": "ok",
    }
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    candles = provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert candles[0].volume == 0.0


def test_error_status_in_body_raises():
    body = {"code": 401, "message": "Invalid API key", "status": "error"}
    session = _session_returning(_response(status_code=200, body=body))
    provider = TwelveDataProvider(api_key="BADKEY", session=session, verify_consistency=False)
    with pytest.raises(DataProviderError, match="Invalid API key"):
        provider.get_candles("XAUUSD", Timeframe.H1, START, END)


def test_non_retryable_http_error_raises_immediately():
    session = _session_returning(_response(status_code=401))
    provider = TwelveDataProvider(api_key="BADKEY", session=session, verify_consistency=False)
    with pytest.raises(DataProviderError):
        provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert session.get.call_count == 1


def test_retryable_error_then_success():
    body = {"meta": {"exchange_timezone": "UTC"}, "values": [], "status": "ok"}
    session = _session_returning(_response(status_code=429), _response(status_code=200, body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        candles = provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert candles == []
    assert session.get.call_count == 2


def test_retryable_error_exhausts_attempts_and_raises():
    session = _session_returning(
        _response(status_code=500), _response(status_code=500), _response(status_code=500)
    )
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        with pytest.raises(DataProviderError):
            provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert session.get.call_count == 3


def test_malformed_candle_row_raises():
    body = {
        "meta": {"exchange_timezone": "UTC"},
        "values": [
            {
                "datetime": "2024-01-15 09:00:00",
                "open": "not-a-number",
                "high": "2",
                "low": "0.5",
                "close": "1.5",
            }
        ],
        "status": "ok",
    }
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    with pytest.raises(DataProviderError):
        provider.get_candles("XAUUSD", Timeframe.H1, START, END)


def test_api_key_never_appears_in_raised_error_message():
    error_response = _response(
        status_code=500, url="https://api.twelvedata.com/time_series?apikey=SECRET123"
    )
    session = _session_returning(error_response, error_response, error_response)
    provider = TwelveDataProvider(api_key="SECRET123", session=session, verify_consistency=False)
    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        with pytest.raises(DataProviderError) as exc_info:
            provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert "SECRET123" not in str(exc_info.value)


def test_empty_api_key_rejected():
    with pytest.raises(ValueError):
        TwelveDataProvider(api_key="")


def _row(dt, price):
    return {
        "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "open": str(price),
        "high": str(price + 1),
        "low": str(price - 1),
        "close": str(price + 0.5),
        "volume": "10",
    }


def _body(rows_ascending):
    return {
        "meta": {"exchange_timezone": "UTC"},
        "values": list(reversed(rows_ascending)),  # API returns descending
        "status": "ok",
    }


def test_paginates_when_span_exceeds_single_request_cap():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=20)  # > ~17 days cap for M5 -> needs 2 pages

    page1_rows = [_row(start + timedelta(minutes=5 * i), 2000 + i) for i in range(3)]
    page2_rows = [_row(end - timedelta(minutes=5 * i), 2100 + i) for i in range(3)]
    session = _session_returning(
        _response(body=_body(page1_rows)), _response(body=_body(page2_rows))
    )
    provider = TwelveDataProvider(
        api_key="KEY", session=session, min_seconds_between_requests=0.01, verify_consistency=False
    )

    with patch("goldsignal.data.twelvedata_provider.time.sleep") as mock_sleep:
        candles = provider.get_candles("XAUUSD", Timeframe.M5, start, end)

    assert session.get.call_count == 2
    mock_sleep.assert_called_once()
    assert len(candles) == 6
    assert candles == sorted(candles, key=lambda c: c.timestamp)


def test_pagination_dedupes_overlapping_boundary_candle():
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=20)
    shared_ts = start + timedelta(minutes=5)

    page1_rows = [_row(start, 2000), _row(shared_ts, 2001)]
    page2_rows = [_row(shared_ts, 9999), _row(end, 2002)]  # duplicate timestamp, different price
    session = _session_returning(
        _response(body=_body(page1_rows)), _response(body=_body(page2_rows))
    )
    provider = TwelveDataProvider(
        api_key="KEY", session=session, min_seconds_between_requests=0.01, verify_consistency=False
    )

    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        candles = provider.get_candles("XAUUSD", Timeframe.M5, start, end)

    timestamps = [c.timestamp for c in candles]
    assert len(timestamps) == len(set(timestamps)) == 3


def test_no_pagination_for_span_within_single_request_cap():
    session = _session_returning(_response(body=_body([_row(START, 2000)])))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    with patch("goldsignal.data.twelvedata_provider.time.sleep") as mock_sleep:
        provider.get_candles("XAUUSD", Timeframe.M5, START, END)
    assert session.get.call_count == 1
    mock_sleep.assert_not_called()


def test_consistency_check_passes_when_spot_checks_agree():
    rows = [_row(START + timedelta(minutes=5 * i), 2000 + i) for i in range(3)]
    bulk_response = _response(body=_body(rows))
    # One spot-check response per sample point (indices 0, 1, 2 -> all three, since n=3)
    spot_responses = [_response(body=_body([r])) for r in rows]
    session = _session_returning(bulk_response, *spot_responses)
    provider = TwelveDataProvider(api_key="KEY", session=session, min_seconds_between_requests=0.01)

    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        candles = provider.get_candles("XAUUSD", Timeframe.M5, START, END)

    assert len(candles) == 3
    assert session.get.call_count == 4  # 1 bulk + 3 spot-checks


def test_consistency_check_raises_on_disagreement():
    rows = [_row(START + timedelta(minutes=5 * i), 2000 + i) for i in range(3)]
    bulk_response = _response(body=_body(rows))
    # Spot-checks agree for indices 0 and 1, but wildly disagree for the last one
    mismatched_row = _row(START + timedelta(minutes=10), 9999)  # same timestamp as rows[2]
    spot_responses = [
        _response(body=_body([rows[0]])),
        _response(body=_body([rows[1]])),
        _response(body=_body([mismatched_row])),
    ]
    session = _session_returning(bulk_response, *spot_responses)
    provider = TwelveDataProvider(api_key="KEY", session=session, min_seconds_between_requests=0.01)

    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        with pytest.raises(DataProviderError, match="consistency check failed"):
            provider.get_candles("XAUUSD", Timeframe.M5, START, END)


def test_consistency_check_skips_gracefully_when_spot_check_is_empty():
    rows = [_row(START, 2000)]
    bulk_response = _response(body=_body(rows))
    empty_spot = _response(body=_body([]))
    session = _session_returning(bulk_response, empty_spot)
    provider = TwelveDataProvider(api_key="KEY", session=session, min_seconds_between_requests=0.01)

    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        candles = provider.get_candles("XAUUSD", Timeframe.M5, START, END)

    assert len(candles) == 1  # no exception despite being unable to verify


def test_get_quote_parses_close_timestamp_and_market_open_without_bid_ask():
    body = {"close": "2450.55", "timestamp": 1705320000, "is_market_open": True}
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)

    quote = provider.get_quote("XAUUSD")

    assert quote.last_price == 2450.55
    assert quote.quote_timestamp == datetime.fromtimestamp(1705320000, tz=UTC)
    assert quote.market_open is True
    assert quote.provider == "twelvedata"
    assert quote.bid is None
    assert quote.ask is None
    assert quote.mid is None
    assert quote.spread is None
    assert quote.price_source.value == "last_trade_price"


def test_get_quote_computes_mid_and_spread_when_bid_ask_present():
    body = {
        "close": "1.0850",
        "timestamp": 1705320000,
        "is_market_open": True,
        "bid": "1.08495",
        "ask": "1.08505",
    }
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)

    quote = provider.get_quote("EURUSD")

    assert quote.bid == 1.08495
    assert quote.ask == 1.08505
    assert quote.mid == pytest.approx(1.085)
    assert quote.spread == pytest.approx(0.0001)
    assert quote.price_source.value == "bid_ask_mid"


def test_get_quote_missing_is_market_open_becomes_none():
    body = {"close": "2450.55", "timestamp": 1705320000}
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    quote = provider.get_quote("XAUUSD")
    assert quote.market_open is None


def test_get_quote_malformed_close_raises():
    body = {"close": "not-a-number", "timestamp": 1705320000}
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    with pytest.raises(DataProviderError):
        provider.get_quote("XAUUSD")


def test_get_quote_missing_timestamp_raises():
    body = {"close": "2450.55"}
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    with pytest.raises(DataProviderError):
        provider.get_quote("XAUUSD")


def test_get_quote_uses_symbol_with_slash():
    body = {"close": "150.25", "timestamp": 1705320000}
    session = _session_returning(_response(body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session, verify_consistency=False)
    provider.get_quote("USDJPY")
    called_params = session.get.call_args.kwargs["params"]
    assert called_params["symbol"] == "USD/JPY"
