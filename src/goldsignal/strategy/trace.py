"""Per-evaluation diagnostic trace, for signal-frequency analysis.

Kept separate from `StrategySignal` (the live/public output) so analysis
tooling gets rich per-candle visibility into *why* a candle did or didn't
produce a signal, without changing `evaluate()`'s contract at all.

Note: when cooldown or the session signal-limit blocks a candle, that
happens *before* indicators are computed (matching the original,
unreordered logic exactly, to avoid any risk of changing live behavior) —
so `conditions`/`candidate_direction` are unavailable for those candles.
This is an accepted, minor gap: cooldown only affects the handful of
candles immediately following a signal, a tiny fraction of any real
walk-forward run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from goldsignal.models.signal import SignalDirection, StrategySignal

INSUFFICIENT_DATA = "insufficient_data"
COOLDOWN_BLOCKED = "cooldown_blocked"
SESSION_LIMIT_BLOCKED = "session_limit_blocked"
INDICATORS_UNAVAILABLE = "indicators_unavailable"
NO_TREND_ALIGNMENT = "no_trend_alignment"
SETUP_FAILED = "setup_failed"
ENTRY_NOT_CONFIRMED = "entry_not_confirmed"
COST_REJECTED = "cost_rejected"
SIGNAL_EMITTED = "signal_emitted"


@dataclass(frozen=True)
class EvaluationTrace:
    timestamp: datetime
    stage: str
    candidate_direction: SignalDirection | None = None
    conditions: dict[str, bool] = field(default_factory=dict)
    signal: StrategySignal | None = None
