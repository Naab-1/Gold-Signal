"""Shared strategy interface, evaluation context, and signal-id derivation.

Concrete strategies (ScalpStrategy, DayTradeStrategy) each implement this
Protocol independently — there is deliberately no shared "evaluate with a
timeframe parameter" base class, so the two modes stay genuinely separate
and separately versioned.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from goldsignal.config import ModeConfig
from goldsignal.models.candle import Candle, Timeframe
from goldsignal.models.signal import SignalDirection, StrategyMode, StrategySignal


@dataclass(frozen=True)
class EvaluationContext:
    """State a caller supplies so cooldown/session-limit rules can be
    enforced without the strategy itself depending on persistence. Phase 1
    strategies are pure functions of (candles, context); Phase 3 wires a
    real context from the Postgres journal.
    """

    last_signal_time: datetime | None = None
    signals_emitted_this_session: int = 0


class Strategy(Protocol):
    mode: StrategyMode
    version: str
    config: ModeConfig

    def evaluate(
        self,
        entry_candles: list[Candle],
        confirmation_candles: list[Candle],
        *,
        now: datetime,
        context: EvaluationContext | None = None,
    ) -> StrategySignal: ...


def make_signal_id(
    *,
    instrument: str,
    strategy_mode: StrategyMode,
    entry_timeframe: Timeframe,
    signal_timestamp: datetime,
    direction: SignalDirection,
    strategy_version: str,
) -> str:
    """Deterministic id from the signal's identity fields — reproducible,
    and distinct across modes/timeframes for the same candle/direction, so
    Phase 3 dedup logic can compare ids directly.
    """
    key = "|".join(
        [
            instrument,
            strategy_mode.value,
            entry_timeframe.value,
            signal_timestamp.isoformat(),
            direction.value,
            strategy_version,
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
