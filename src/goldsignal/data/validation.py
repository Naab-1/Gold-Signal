"""Candle validation: catches missing/duplicate/out-of-order candles, stale
data, and malformed OHLCV values before anything reaches the strategy.

Every drop is recorded as a human-readable issue string, so callers can log
*why* data (and therefore a signal) was accepted or rejected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from goldsignal.models.candle import Candle, Timeframe
from goldsignal.utils.time import require_utc

DEFAULT_MAX_STALENESS_MULTIPLIER = 2.0


@dataclass(frozen=True)
class ValidationResult:
    clean_candles: list[Candle]
    issues: list[str] = field(default_factory=list)
    is_stale: bool = False

    @property
    def is_usable(self) -> bool:
        return bool(self.clean_candles) and not self.is_stale


def _malformed_reasons(c: Candle) -> list[str]:
    reasons: list[str] = []
    values = (c.open, c.high, c.low, c.close, c.volume)
    if not all(math.isfinite(v) for v in values):
        reasons.append("non_finite_value")
        return reasons  # further checks are meaningless on non-finite data
    if c.high < c.low:
        reasons.append("high_below_low")
    if not (c.low <= c.open <= c.high):
        reasons.append("open_outside_high_low_range")
    if not (c.low <= c.close <= c.high):
        reasons.append("close_outside_high_low_range")
    if c.volume < 0:
        reasons.append("negative_volume")
    if c.close <= 0:
        reasons.append("non_positive_close")
    return reasons


def validate_candles(
    candles: list[Candle],
    timeframe: Timeframe,
    now: datetime,
    max_staleness_multiplier: float = DEFAULT_MAX_STALENESS_MULTIPLIER,
) -> ValidationResult:
    """Validate `candles` (assumed given in ascending timestamp order).

    Drops malformed, duplicate, and out-of-order candles. Gaps versus the
    expected timeframe interval are reported as issues but do not remove
    any candle. Staleness is checked against `now` (must be UTC).
    """
    require_utc(now, field_name="now")

    issues: list[str] = []
    clean: list[Candle] = []
    last_kept_ts: datetime | None = None

    for c in candles:
        reasons = _malformed_reasons(c)
        if reasons:
            issues.append(
                f"{c.timestamp.isoformat()}: dropped malformed candle ({', '.join(reasons)})"
            )
            continue

        if last_kept_ts is not None:
            if c.timestamp == last_kept_ts:
                issues.append(f"{c.timestamp.isoformat()}: dropped duplicate timestamp")
                continue
            if c.timestamp < last_kept_ts:
                issues.append(
                    f"{c.timestamp.isoformat()}: dropped out-of-order candle "
                    f"(before last kept {last_kept_ts.isoformat()})"
                )
                continue
            expected = last_kept_ts + timeframe.duration
            if c.timestamp > expected:
                missing = int((c.timestamp - expected) / timeframe.duration) + 1
                issues.append(
                    f"gap detected between {last_kept_ts.isoformat()} and "
                    f"{c.timestamp.isoformat()} (~{missing} missing candle(s))"
                )

        clean.append(c)
        last_kept_ts = c.timestamp

    is_stale = False
    if clean:
        max_age = timeframe.duration * max_staleness_multiplier
        age = now - clean[-1].timestamp
        if age > max_age:
            is_stale = True
            issues.append(
                f"stale data: latest candle {clean[-1].timestamp.isoformat()} is "
                f"{age} old, exceeding max age {max_age} for timeframe {timeframe.value}"
            )
    else:
        issues.append("no valid candles after validation")

    return ValidationResult(clean_candles=clean, issues=issues, is_stale=is_stale)
