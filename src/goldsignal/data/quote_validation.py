"""Pure quote-safety checks: staleness, excessive spread, and demo-broker
price comparison. Kept independent fields on `QuoteAssessment` rather than
one collapsed flag, so "handle market closures and unavailable quotes
explicitly" means each condition is separately visible — a report can
distinguish "spread unknown because this provider doesn't supply one" from
"spread is known and within limits" from "spread is known and excessive,"
rather than defaulting all three to the same falsy value.

A quote that's genuinely unobtainable (network/API failure) is a fourth,
distinct state handled by the caller (a per-instrument try/except around
`provider.get_quote`), not represented here — there is no "empty" Quote.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from goldsignal.instruments import InstrumentProfile
from goldsignal.models.quote import Quote


def is_quote_stale(quote: Quote, now: datetime, max_age: timedelta) -> bool:
    return (now - quote.quote_timestamp) > max_age


@dataclass(frozen=True)
class QuoteAssessment:
    quote: Quote
    is_stale: bool
    spread_exceeds_max: bool | None  # None = spread not supplied by the provider
    broker_price: float | None
    broker_diff: float | None
    broker_mismatch: bool | None  # None if no broker price was supplied


def assess_quote(
    quote: Quote,
    profile: InstrumentProfile,
    now: datetime,
    *,
    max_quote_age: timedelta,
    broker_price: float | None = None,
    broker_tolerance: float | None = None,
) -> QuoteAssessment:
    spread_exceeds_max = (
        quote.spread > profile.max_permitted_spread if quote.spread is not None else None
    )

    broker_diff: float | None = None
    broker_mismatch: bool | None = None
    if broker_price is not None:
        reference_price = quote.mid if quote.mid is not None else quote.last_price
        broker_diff = broker_price - reference_price
        tolerance = (
            broker_tolerance if broker_tolerance is not None else profile.broker_price_tolerance
        )
        broker_mismatch = abs(broker_diff) > tolerance

    return QuoteAssessment(
        quote=quote,
        is_stale=is_quote_stale(quote, now, max_quote_age),
        spread_exceeds_max=spread_exceeds_max,
        broker_price=broker_price,
        broker_diff=broker_diff,
        broker_mismatch=broker_mismatch,
    )
