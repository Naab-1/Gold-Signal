"""A single live price quote for one instrument.

Deliberately separate from `Candle` (OHLCV history) — a `Quote` is "the
current price right now," which may or may not include a real bid/ask
depending on what the configured provider's plan actually returns.
`__post_init__` structurally enforces "never fabricate a spread that
wasn't observed": bid/ask must arrive together, and whenever they're
present, mid/spread must have actually been derived from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from goldsignal.utils.time import require_utc


class PriceSource(str, Enum):
    BID_ASK_MID = "bid_ask_mid"
    LAST_TRADE_PRICE = "last_trade_price"


@dataclass(frozen=True)
class Quote:
    instrument: str
    provider: str
    quote_timestamp: datetime
    last_price: float
    price_source: PriceSource
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    spread: float | None = None
    market_open: bool | None = None  # None = provider didn't report it

    def __post_init__(self) -> None:
        require_utc(self.quote_timestamp, field_name="Quote.quote_timestamp")
        if (self.bid is None) != (self.ask is None):
            raise ValueError("bid and ask must both be present or both be None")
        if self.bid is not None and (self.mid is None or self.spread is None):
            raise ValueError("mid and spread must be derived whenever bid/ask are present")
