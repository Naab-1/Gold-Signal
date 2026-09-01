"""Candle (OHLCV bar) and Timeframe models.

Timestamps are always stored internally in UTC, per GoldSignal's data
contract — never assume a local timezone when reading or writing candles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from goldsignal.utils.time import require_utc


class Timeframe(str, Enum):
    """Supported candle timeframes.

    Only H1 is used by the strategy in Phase 1; the others are reserved so
    the data-provider interface can support additional timeframes later
    without a breaking change.
    """

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def duration(self) -> timedelta:
        return _TIMEFRAME_DURATIONS[self]


_TIMEFRAME_DURATIONS: dict[Timeframe, timedelta] = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.M30: timedelta(minutes=30),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
}


@dataclass(frozen=True)
class Candle:
    """A single OHLCV bar.

    Only structural validity (a UTC, timezone-aware timestamp) is enforced
    here. Business-rule sanity checks (e.g. high >= low, non-negative
    volume) are the responsibility of `goldsignal.data.validation`, so that
    malformed candles can still be constructed in tests that exercise that
    validation.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        require_utc(self.timestamp, field_name="Candle.timestamp")
