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

Consistency safeguard: after assembling a result, a few sample points
(first/middle/last candle) are independently re-fetched and compared
against the bulk result. If they disagree beyond a generous tolerance,
the whole batch is rejected with DataProviderError rather than silently
used — this was added after TwelveData was observed, mid-session, to
serve a historical XAU/USD range at roughly half its real price level,
self-correcting a few hours later with no error or warning of any kind.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import requests

from goldsignal.models.candle import Candle, Timeframe
from goldsignal.models.quote import PriceSource, Quote

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com/time_series"
_QUOTE_URL = "https://api.twelvedata.com/quote"

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
_RETRY_BACKOFF_SECONDS = 15.0

# TwelveData documents outputsize as capped at 5000 rows per request. A
# wide date range needing more candles than that is paginated as several
# requests, each safely under the cap, paced to stay under the free
# tier's 8-requests/minute limit. Backoff on 429 is deliberately patient
# (15s/30s/45s) since a per-minute cap needs to actually roll over, not
# just a brief pause.
_MAX_CANDLES_PER_REQUEST = 4900
_DEFAULT_MIN_SECONDS_BETWEEN_REQUESTS = 10.0

# Generous — well above normal rounding/timing noise, but would have
# immediately caught the ~80% discrepancy that motivated this check.
_CONSISTENCY_TOLERANCE_FRACTION = 0.05


class DataProviderError(RuntimeError):
    """Raised on any non-success response or malformed payload. Never
    silently swallowed — callers must fail closed on this.
    """


def _mask(url: str, api_key: str) -> str:
    return url.replace(api_key, "***")


def _parse_optional_price(raw: object) -> float | None:
    """Defensive bid/ask parsing: absent, null, or unparseable all become
    None (bid/ask genuinely not supplied) — never a fabricated fallback.
    """
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class TwelveDataProvider:
    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        min_seconds_between_requests: float = _DEFAULT_MIN_SECONDS_BETWEEN_REQUESTS,
        verify_consistency: bool = True,
    ):
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._api_key = api_key
        self._session = session or requests.Session()
        self._min_seconds_between_requests = min_seconds_between_requests
        self._verify_consistency_enabled = verify_consistency

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
            candles = self._get_candles_page(instrument, timeframe, start, end)
        else:
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
            candles = sorted(candles_by_timestamp.values(), key=lambda c: c.timestamp)

        if self._verify_consistency_enabled and candles:
            self._verify_consistency(instrument, timeframe, candles)

        return candles

    def _verify_consistency(
        self, instrument: str, timeframe: Timeframe, candles: list[Candle]
    ) -> None:
        """Independently re-fetch a few sample points and compare against
        the bulk result. Raises DataProviderError on disagreement rather
        than silently returning data that might be wrong.
        """
        n = len(candles)
        sample_indices = sorted({0, n // 2, n - 1})
        for idx in sample_indices:
            target = candles[idx]
            time.sleep(self._min_seconds_between_requests)
            spot = self._get_candles_page(
                instrument, timeframe, target.timestamp, target.timestamp + timeframe.duration
            )
            spot_candle = next((c for c in spot if c.timestamp == target.timestamp), None)
            if spot_candle is None:
                continue  # couldn't independently verify this point; don't fail on that alone

            reference = max(abs(target.close), 1e-9)
            diff_fraction = abs(spot_candle.close - target.close) / reference
            if diff_fraction > _CONSISTENCY_TOLERANCE_FRACTION:
                raise DataProviderError(
                    f"Data consistency check failed for {instrument} {timeframe.value} at "
                    f"{target.timestamp.isoformat()}: bulk-fetched close={target.close:.4f} but "
                    f"a fresh spot-check close={spot_candle.close:.4f} "
                    f"({diff_fraction:.1%} apart, exceeds {_CONSISTENCY_TOLERANCE_FRACTION:.0%} "
                    "tolerance) — the provider may be returning inconsistent historical data; "
                    "refusing to use this batch."
                )

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

        payload = self._request(_BASE_URL, params)
        return self._parse(payload)

    def get_quote(self, instrument: str) -> Quote:
        symbol = instrument if "/" in instrument else f"{instrument[:3]}/{instrument[3:]}"
        payload = self._request(_QUOTE_URL, {"symbol": symbol, "apikey": self._api_key})
        return self._parse_quote(instrument, payload)

    def _parse_quote(self, instrument: str, payload: dict) -> Quote:
        try:
            last_price = float(payload["close"])
            quote_timestamp = datetime.fromtimestamp(int(payload["timestamp"]), tz=UTC)
        except (KeyError, TypeError, ValueError) as exc:
            raise DataProviderError(f"TwelveData returned a malformed quote: {payload!r}") from exc

        market_open = payload.get("is_market_open")
        if not isinstance(market_open, bool):
            market_open = None

        bid = _parse_optional_price(payload.get("bid"))
        ask = _parse_optional_price(payload.get("ask"))
        if bid is not None and ask is not None:
            mid = (bid + ask) / 2
            spread = ask - bid
            price_source = PriceSource.BID_ASK_MID
        else:
            bid = ask = mid = spread = None
            price_source = PriceSource.LAST_TRADE_PRICE

        return Quote(
            instrument=instrument,
            provider="twelvedata",
            quote_timestamp=quote_timestamp,
            last_price=last_price,
            price_source=price_source,
            bid=bid,
            ask=ask,
            mid=mid,
            spread=spread,
            market_open=market_open,
        )

    def _request(self, url: str, params: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = self._session.get(url, params=params, timeout=15)
            except requests.exceptions.RequestException as exc:
                # A connection-level failure (timeout, reset, DNS) never
                # reached a response at all -- retry it exactly like a
                # retryable HTTP status, rather than crashing immediately.
                masked_url = _mask(url, self._api_key)
                last_error = DataProviderError(
                    f"TwelveData request failed with {exc.__class__.__name__} "
                    f"(attempt {attempt}/{_MAX_ATTEMPTS}): {masked_url}"
                )
                logger.warning(str(last_error))
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise last_error from exc

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
