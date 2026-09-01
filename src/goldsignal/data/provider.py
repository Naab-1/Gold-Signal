"""Data provider interface.

Any market-data source (mock, or a real vendor added in a later phase)
implements this Protocol, so the rest of GoldSignal never depends on a
specific vendor's API shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from goldsignal.models.candle import Candle, Timeframe


class DataProvider(Protocol):
    def get_candles(
        self,
        instrument: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """Return closed candles for `instrument`/`timeframe` in [start, end], UTC.

        Implementations must return candles sorted ascending by timestamp,
        with no duplicates, and must raise rather than silently return
        malformed data.
        """
        ...


def get_data_provider(settings) -> DataProvider:  # GlobalSettings, avoiding an import cycle here
    """Build the configured DataProvider. Only "mock" and "twelvedata" exist
    so far; anything else fails closed rather than guessing a fallback.
    """
    from goldsignal.config import ConfigError
    from goldsignal.data.mock_provider import MockDataProvider
    from goldsignal.data.twelvedata_provider import TwelveDataProvider

    if settings.data_provider == "mock":
        return MockDataProvider()
    if settings.data_provider == "twelvedata":
        return TwelveDataProvider(api_key=settings.twelvedata_api_key)
    raise ConfigError(
        f"GOLDSIGNAL_DATA_PROVIDER={settings.data_provider!r} is not implemented "
        "(only 'mock' and 'twelvedata' exist)"
    )
