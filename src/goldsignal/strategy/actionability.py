"""Is a just-evaluated BUY/SELL signal still safe to alert on?

A signal discovered during a catch-up sweep (the candle that produced it
closed some time ago, not just now) may no longer represent a live
opportunity: price could already have run past the stop-loss or a target,
or the setup's own expiration could already have passed. Sending it as if
it were fresh would misrepresent a stale idea as an actionable one — this
is the machine-checkable version of the spec's "confirm the current price
remains inside the valid entry zone and the setup hasn't expired or been
invalidated" requirement, for the market-order A+ signal shape in use
today (an explicit price-zone/expiration field set is watchlist-workflow
territory, deferred until the A tier activates).
"""

from __future__ import annotations

from datetime import datetime

from goldsignal.models.signal import SignalDirection, StrategySignal


def is_still_actionable(
    signal: StrategySignal, *, now: datetime, latest_price: float
) -> tuple[bool, str]:
    """Returns (True, "") if `signal` is still safe to alert on, else
    (False, reason). Only meaningful for BUY/SELL signals.
    """
    if signal.direction not in (SignalDirection.BUY, SignalDirection.SELL):
        raise ValueError("is_still_actionable is only for BUY/SELL signals")

    if signal.setup_expiration is not None and now > signal.setup_expiration:
        return False, "setup expired before it could be alerted"

    is_buy = signal.direction == SignalDirection.BUY
    if signal.stop_loss is not None:
        stop_hit = latest_price <= signal.stop_loss if is_buy else latest_price >= signal.stop_loss
        if stop_hit:
            return False, "price already reached the stop-loss level"

    for target in signal.targets:
        target_hit = latest_price >= target.price if is_buy else latest_price <= target.price
        if target_hit:
            return False, f"price already reached {target.label}"

    return True, ""
