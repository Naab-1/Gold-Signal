"""TwelveData market-data provider.

Verified against TwelveData's public docs (https://twelvedata.com/docs):
GET https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=...&apikey=...
returns {"meta": {..., "exchange_timezone": "..."}, "values": [...], "status": "ok"}
on success, or {"code": ..., "message": ..., "status": "error"} on failure.

Two response quirks handled here:
- `values` are in DESCENDING time order (most recent first) — reversed to
  match the DataProvider contract (ascending).
- `datetime` values are in the exchange's LOCAL timezone (`meta.exchange_timezone`),
  never UTC — converted before constructing any Candle, since Candle
  requires a UTC timestamp.

Never logs the API key, even when logging the request (masked in the URL).
Fails closed: any non-2xx status or a body with "status": "error" raises
DataProviderError with the provider's own code/message — never returns
partial or fabricated data.

`outputsize` is documented as capped at 5000 rows per request. A wide
date range needing more candles than that is transparently paginated as
several requests (each safely under the cap), paced to stay under the
free tier's 8-requests/minute limit, then merged/deduped/sorted.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from goldsignal.models.candle import Candle, Timeframe

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com/time_series"

_TIMEFRAME_TO_INTERVAL = {
    Timeframe.M1: "1min",
    Timeframe.M5: "5min",
    Timeframe.M15: "15min",
    Timeframe.M30: "30min",
    Timeframe.H1: "1h",
    Timeframe.H4: "4h",
    Timeframe.D1: "1day",
}

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 2.0

# TwelveData documents outputsize as capped at 5000 rows per request. A
# wide date range needing more candles than that is paginated as several
# requests, each safely under the cap, paced to stay under the free
# tier's 8-requests/minute limit.
_MAX_CANDLES_PER_REQUEST = 4900
_DEFAULT_MIN_SECONDS_BETWEEN_REQUESTS = 8.0


class DataProviderError(RuntimeError):
    """Raised on any non-success response or malformed payload. Never
    silently swallowed — callers must fail closed on this.
    """


def _mask(url: str, api_key: str) -> str:
    return url.replace(api_key, "***")


class TwelveDataProvider:
    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        min_seconds_between_requests: float = _DEFAULT_MIN_SECONDS_BETWEEN_REQUESTS,
    ):
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._api_key = api_key
        self._session = session or requests.Session()
        self._min_seconds_between_requests = min_seconds_between_requests

    def get_candles(
        self,
        instrument: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        if timeframe not in _TIMEFRAME_TO_INTERVAL:
            raise ValueError(f"unsupported timeframe for TwelveData: {timeframe}")

        max_span = timeframe.duration * _MAX_CANDLES_PER_REQUEST
        if end - start <= max_span:
            return self._get_candles_page(instrument, timeframe, start, end)

        candles_by_timestamp: dict[datetime, Candle] = {}
        chunk_start = start
        first_request = True
        while chunk_start < end:
            if not first_request:
                time.sleep(self._min_seconds_between_requests)
            first_request = False
            chunk_end = min(chunk_start + max_span, end)
            for c in self._get_candles_page(instrument, timeframe, chunk_start, chunk_end):
                candles_by_timestamp[c.timestamp] = c
            chunk_start = chunk_end

        return sorted(candles_by_timestamp.values(), key=lambda c: c.timestamp)

    def _get_candles_page(
        self,
        instrument: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        symbol = instrument if "/" in instrument else f"{instrument[:3]}/{instrument[3:]}"

        params = {
            "symbol": symbol,
            "interval": _TIMEFRAME_TO_INTERVAL[timeframe],
            "apikey": self._api_key,
            "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
            "outputsize": 5000,
            "timezone": "UTC",
        }

        payload = self._request(params)
        return self._parse(payload)

    def _request(self, params: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            response = self._session.get(_BASE_URL, params=params, timeout=15)
            masked_url = _mask(response.url, self._api_key)

            if response.status_code in _RETRYABLE_STATUS_CODES:
                last_error = DataProviderError(
                    f"TwelveData request failed with HTTP {response.status_code} "
                    f"(attempt {attempt}/{_MAX_ATTEMPTS}): {masked_url}"
                )
                logger.warning(str(last_error))
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise last_error

            if response.status_code != 200:
                raise DataProviderError(
                    f"TwelveData request failed with HTTP {response.status_code}: {masked_url}"
                )

            try:
                body = response.json()
            except ValueError as exc:
                raise DataProviderError(
                    f"TwelveData returned non-JSON response: {masked_url}"
                ) from exc

            if body.get("status") == "error":
                raise DataProviderError(
                    f"TwelveData error {body.get('code')}: {body.get('message')}"
                )
            return body

        raise last_error  # pragma: no cover - unreachable, loop always returns or raises

    def _parse(self, payload: dict) -> list[Candle]:
        meta = payload.get("meta")
        values = payload.get("values")
        if meta is None or values is None:
            raise DataProviderError(f"TwelveData response missing meta/values: {payload!r}")

        # `timezone=UTC` was requested, so exchange_timezone should already
        # reflect that; parse defensively in case the API ignores the param.
        tz_name = meta.get("exchange_timezone", "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except Exception as exc:  # noqa: BLE001 - any zoneinfo failure should fail closed
            raise DataProviderError(f"TwelveData returned unknown timezone {tz_name!r}") from exc

        candles: list[Candle] = []
        for row in values:
            try:
                naive = datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                naive = datetime.strptime(row["datetime"], "%Y-%m-%d")
            localized = naive.replace(tzinfo=tz)
            utc_timestamp = localized.astimezone(ZoneInfo("UTC"))

            try:
                candles.append(
                    Candle(
                        timestamp=utc_timestamp,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume") or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise DataProviderError(
                    f"TwelveData returned a malformed candle row: {row!r}"
                ) from exc

        candles.sort(
            key=lambda c: c.timestamp
        )  # API returns descending; contract requires ascending
        return candles
