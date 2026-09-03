"""Data provider interface.

Any market-data source (mock, or a real vendor added in a later phase)
implements this Protocol, so the rest of GoldSignal never depends on a
specific vendor's API shape.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from goldsignal.models.candle import Candle, Timeframe
from goldsignal.models.quote import Quote


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

    def get_quote(self, instrument: str) -> Quote:
        """Return the current price for `instrument`.

        Must raise `DataProviderError` if a quote genuinely can't be
        obtained; must leave bid/ask/mid/spread as None when the provider
        doesn't supply them — never synthesize an unobserved spread.
        """
        ...


def get_data_provider(settings, *, verify_consistency: bool = True) -> DataProvider:
    # GlobalSettings, avoiding an import cycle here
    """Build the configured DataProvider. Only "mock" and "twelvedata" exist
    so far; anything else fails closed rather than guessing a fallback.

    `verify_consistency` defaults to True (the spot-check safeguard added
    after TwelveData was once observed serving a silently-corrupted
    historical range) -- pass False for high-frequency live polling of a
    small rolling window, where it multiplies request volume by 4x for a
    much smaller risk surface than a one-off bulk historical pull (live
    catch-up only ever acts on the freshest candle(s); it never re-reads
    deep history the way an analysis/backtest run does).
    """
    from goldsignal.config import ConfigError
    from goldsignal.data.mock_provider import MockDataProvider
    from goldsignal.data.twelvedata_provider import TwelveDataProvider

    if settings.data_provider == "mock":
        return MockDataProvider()
    if settings.data_provider == "twelvedata":
        return TwelveDataProvider(
            api_key=settings.twelvedata_api_key, verify_consistency=verify_consistency
        )
    raise ConfigError(
        f"GOLDSIGNAL_DATA_PROVIDER={settings.data_provider!r} is not implemented "
        "(only 'mock' and 'twelvedata' exist)"
    )
