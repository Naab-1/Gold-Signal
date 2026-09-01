from datetime import UTC, datetime
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
    provider = TwelveDataProvider(api_key="SECRET123", session=session)

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
    provider = TwelveDataProvider(api_key="KEY", session=session)
    candles = provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert candles[0].volume == 0.0


def test_error_status_in_body_raises():
    body = {"code": 401, "message": "Invalid API key", "status": "error"}
    session = _session_returning(_response(status_code=200, body=body))
    provider = TwelveDataProvider(api_key="BADKEY", session=session)
    with pytest.raises(DataProviderError, match="Invalid API key"):
        provider.get_candles("XAUUSD", Timeframe.H1, START, END)


def test_non_retryable_http_error_raises_immediately():
    session = _session_returning(_response(status_code=401))
    provider = TwelveDataProvider(api_key="BADKEY", session=session)
    with pytest.raises(DataProviderError):
        provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert session.get.call_count == 1


def test_retryable_error_then_success():
    body = {"meta": {"exchange_timezone": "UTC"}, "values": [], "status": "ok"}
    session = _session_returning(_response(status_code=429), _response(status_code=200, body=body))
    provider = TwelveDataProvider(api_key="KEY", session=session)
    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        candles = provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert candles == []
    assert session.get.call_count == 2


def test_retryable_error_exhausts_attempts_and_raises():
    session = _session_returning(
        _response(status_code=500), _response(status_code=500), _response(status_code=500)
    )
    provider = TwelveDataProvider(api_key="KEY", session=session)
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
    provider = TwelveDataProvider(api_key="KEY", session=session)
    with pytest.raises(DataProviderError):
        provider.get_candles("XAUUSD", Timeframe.H1, START, END)


def test_api_key_never_appears_in_raised_error_message():
    error_response = _response(
        status_code=500, url="https://api.twelvedata.com/time_series?apikey=SECRET123"
    )
    session = _session_returning(error_response, error_response, error_response)
    provider = TwelveDataProvider(api_key="SECRET123", session=session)
    with patch("goldsignal.data.twelvedata_provider.time.sleep"):
        with pytest.raises(DataProviderError) as exc_info:
            provider.get_candles("XAUUSD", Timeframe.H1, START, END)
    assert "SECRET123" not in str(exc_info.value)


def test_empty_api_key_rejected():
    with pytest.raises(ValueError):
        TwelveDataProvider(api_key="")
