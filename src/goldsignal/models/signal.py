"""Strategy signal model.

A StrategySignal is the sole output of a strategy's `evaluate()` call. Its
`confidence_score` is a count of satisfied rule conditions expressed as a
percentage — it is NOT a probability of profit and must never be presented
as one (in code, logs, Telegram messages, or documentation).

Every BUY/SELL signal carries 1-3 profit targets (TP1..TP3). Each target's
`r_multiple` is the *gross* reward-to-risk ratio ((price - entry) / risk) —
the cost-of-trading-adjusted ("net") reward is only used internally as the
acceptance threshold when the targets are selected (see strategy/targets.py)
and is not a separate stored field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from goldsignal.models.candle import Timeframe
from goldsignal.utils.time import require_utc


class StrategyMode(str, Enum):
    SCALP = "SCALP"
    DAY_TRADE = "DAY_TRADE"
    # STRATEGY RESEARCH AND REPLACEMENT program, Phase 4 candidate families
    # (see docs/phase4_trend_pullback.md) -- independent of the frozen
    # SCALP/DAY_TRADE A+/A-tier baseline, never combined with it.
    TREND_PULLBACK = "TREND_PULLBACK"
    BREAKOUT_CONTINUATION = "BREAKOUT_CONTINUATION"
    BREAKOUT_AND_RETEST = "BREAKOUT_AND_RETEST"


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class EntryOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    CONFIRMATION = "CONFIRMATION"


_TARGET_LABELS = ("TP1", "TP2", "TP3")


@dataclass(frozen=True)
class ProfitTarget:
    label: str  # "TP1", "TP2", or "TP3"
    price: float
    r_multiple: float  # gross reward-to-risk at this target

    def __post_init__(self) -> None:
        if self.label not in _TARGET_LABELS:
            raise ValueError(f"target label must be one of {_TARGET_LABELS}, got {self.label!r}")
        if self.r_multiple <= 0:
            raise ValueError("target r_multiple must be positive")


def _validate_targets(
    direction: SignalDirection, entry_price: float, targets: list[ProfitTarget]
) -> None:
    if not targets:
        raise ValueError("BUY/SELL signals must include at least one profit target (TP1)")
    if len(targets) > 3:
        raise ValueError("at most 3 profit targets (TP1..TP3) are allowed")

    expected_labels = list(_TARGET_LABELS[: len(targets)])
    labels = [t.label for t in targets]
    if labels != expected_labels:
        raise ValueError(f"targets must be labeled {expected_labels} in order, got {labels}")

    prices = [t.price for t in targets]
    if len(set(prices)) != len(prices):
        raise ValueError("duplicate target prices are not allowed")

    r_multiples = [t.r_multiple for t in targets]
    if r_multiples != sorted(r_multiples):
        raise ValueError("target r_multiples must strictly increase from TP1 to TP3")

    if direction == SignalDirection.BUY:
        if any(p <= entry_price for p in prices):
            raise ValueError("BUY targets must be above entry")
        if prices != sorted(prices):
            raise ValueError("BUY targets must be ordered increasing (TP1 < TP2 < TP3)")
    else:
        if any(p >= entry_price for p in prices):
            raise ValueError("SELL targets must be below entry")
        if prices != sorted(prices, reverse=True):
            raise ValueError("SELL targets must be ordered decreasing (TP1 > TP2 > TP3)")


@dataclass(frozen=True)
class StrategySignal:
    signal_id: str
    instrument: str
    strategy_mode: StrategyMode
    strategy_version: str
    entry_timeframe: Timeframe
    confirmation_timeframe: Timeframe
    direction: SignalDirection
    signal_timestamp: datetime

    # Trade parameters — all None for NO_TRADE signals.
    entry_price: float | None
    entry_order_type: EntryOrderType | None
    stop_loss: float | None
    targets: list[ProfitTarget]
    setup_expiration: datetime | None
    invalidation_conditions: list[str]
    estimated_spread: float | None
    estimated_slippage: float | None

    # Transparency: exactly which rule conditions passed/failed.
    conditions_met: list[str] = field(default_factory=list)
    conditions_failed: list[str] = field(default_factory=list)

    # Fraction of evaluated rule conditions satisfied, as a 0-100 score.
    # Derived only from rule confirmations — not a probability of profit.
    confidence_score: float = 0.0

    # Short human-readable summary, e.g. for logs and Telegram messages.
    reason: str = ""

    def __post_init__(self) -> None:
        require_utc(self.signal_timestamp, field_name="StrategySignal.signal_timestamp")

        if self.direction == SignalDirection.NO_TRADE:
            trade_fields = (
                self.entry_price,
                self.entry_order_type,
                self.stop_loss,
                self.setup_expiration,
                self.estimated_spread,
                self.estimated_slippage,
            )
            if any(v is not None for v in trade_fields):
                raise ValueError("NO_TRADE signals must not carry trade parameters")
            if self.targets:
                raise ValueError("NO_TRADE signals must not carry profit targets")
            return

        if self.entry_price is None or self.entry_order_type is None or self.stop_loss is None:
            raise ValueError(
                f"{self.direction} signals require entry_price, entry_order_type, stop_loss"
            )
        if self.estimated_spread is None or self.estimated_slippage is None:
            raise ValueError(
                f"{self.direction} signals require estimated_spread and estimated_slippage"
            )
        if self.estimated_spread < 0 or self.estimated_slippage < 0:
            raise ValueError("estimated_spread and estimated_slippage must not be negative")

        if self.direction == SignalDirection.BUY and self.stop_loss >= self.entry_price:
            raise ValueError("BUY stop_loss must be below entry_price")
        if self.direction == SignalDirection.SELL and self.stop_loss <= self.entry_price:
            raise ValueError("SELL stop_loss must be above entry_price")

        _validate_targets(self.direction, self.entry_price, self.targets)

        if self.setup_expiration is None:
            raise ValueError(f"{self.direction} signals require setup_expiration")
        require_utc(self.setup_expiration, field_name="StrategySignal.setup_expiration")
        if self.setup_expiration <= self.signal_timestamp:
            raise ValueError("setup_expiration must be after signal_timestamp")
