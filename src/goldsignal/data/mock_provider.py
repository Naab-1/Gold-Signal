"""Deterministic synthetic OHLCV data provider, for Phase 1 development and tests.

This is the ONLY data provider wired up in Phase 1. It never makes network
calls. The price series is a seeded pseudo-random walk anchored to a base
price — it is not real market data and must never be used for anything
beyond local development/testing until a real provider (Phase 3) is added.

Note on determinism: each call reseeds its random generator from
(seed, instrument, timeframe), so the *shape* of the walk is reproducible
per call, but it is indexed by "steps since `start`" rather than by
absolute calendar time — two calls with different `start` values will not
splice into one continuous series. That's an acceptable simplification for
a mock provider.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from goldsignal.models.candle import Candle, Timeframe
from goldsignal.utils.time import require_utc

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _align_up(dt: datetime, step: timedelta) -> datetime:
    """Round `dt` up to the next multiple of `step` since the Unix epoch."""
    remainder = (dt - _EPOCH) % step
    if remainder == timedelta(0):
        return dt
    return dt + (step - remainder)


class MockDataProvider:
    def __init__(self, seed: int = 42, base_price: float = 2400.0, volatility: float = 3.0):
        if volatility <= 0:
            raise ValueError("volatility must be positive")
        self._seed = seed
        self._base_price = base_price
        self._volatility = volatility

    def get_candles(
        self,
        instrument: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        require_utc(start, field_name="start")
        require_utc(end, field_name="end")
        if end < start:
            raise ValueError("end must not be before start")

        step = timeframe.duration
        timestamps: list[datetime] = []
        t = _align_up(start, step)
        while t <= end:
            timestamps.append(t)
            t += step

        rng = random.Random(f"{self._seed}:{instrument}:{timeframe.value}")
        candles: list[Candle] = []
        price = self._base_price
        for ts in timestamps:
            open_price = price
            close_price = max(0.01, open_price + rng.gauss(0, self._volatility))
            wick = abs(rng.gauss(0, self._volatility / 3))
            high = max(open_price, close_price) + wick
            low = max(0.01, min(open_price, close_price) - wick)
            volume = abs(rng.gauss(1000.0, 200.0))
            candles.append(
                Candle(
                    timestamp=ts,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close_price,
                    volume=volume,
                )
            )
            price = close_price
        return candles
