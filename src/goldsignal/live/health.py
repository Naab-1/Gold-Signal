"""Pure scheduler-health evaluation: given the raw facts (last successful
run, last processed candle, expected cadence), decide whether the
scheduler/data-feed is healthy and whether a health/recovery Telegram
notice needs sending — kept free of any DB or Telegram I/O so gap
scenarios can be tested directly.

"Two expected scan intervals missed" (per spec) means unhealthy once more
than `2 * EXPECTED_SCAN_INTERVAL` has passed since the last *successful*
run — independent of the strategy's own candle timeframe, since the
scheduler is expected to fire (and cheaply no-op when there's nothing new
to process) every `EXPECTED_SCAN_INTERVAL` regardless of mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

EXPECTED_SCAN_INTERVAL = timedelta(minutes=5)
UNHEALTHY_AFTER = EXPECTED_SCAN_INTERVAL * 2


class AlertAction(str, Enum):
    NONE = "none"
    SEND_HEALTH_ALERT = "send_health_alert"
    SEND_RECOVERY_ALERT = "send_recovery_alert"


@dataclass(frozen=True)
class HealthSnapshot:
    strategy_mode: str
    now: datetime
    last_successful_run_at: datetime | None
    last_processed_candle: datetime | None
    expected_latest_closed_candle: datetime | None
    unprocessed_candle_count: int
    missed_setups_recent_count: int
    gap_since_last_success: timedelta | None
    is_healthy: bool


def evaluate_health(
    *,
    strategy_mode: str,
    now: datetime,
    last_successful_run_at: datetime | None,
    last_processed_candle: datetime | None,
    expected_latest_closed_candle: datetime | None,
    entry_duration: timedelta,
    missed_setups_recent_count: int = 0,
) -> HealthSnapshot:
    gap = (now - last_successful_run_at) if last_successful_run_at is not None else None
    is_healthy = gap is None or gap <= UNHEALTHY_AFTER

    unprocessed_count = 0
    if expected_latest_closed_candle is not None:
        baseline = last_processed_candle if last_processed_candle is not None else now
        if expected_latest_closed_candle > baseline:
            unprocessed_count = max(
                0, int((expected_latest_closed_candle - baseline) / entry_duration)
            )

    return HealthSnapshot(
        strategy_mode=strategy_mode,
        now=now,
        last_successful_run_at=last_successful_run_at,
        last_processed_candle=last_processed_candle,
        expected_latest_closed_candle=expected_latest_closed_candle,
        unprocessed_candle_count=unprocessed_count,
        missed_setups_recent_count=missed_setups_recent_count,
        gap_since_last_success=gap,
        is_healthy=is_healthy,
    )


def decide_alert_action(snapshot: HealthSnapshot, *, previously_healthy: bool) -> AlertAction:
    """A pure state-transition decision: only fires on a change, never on
    every run while already unhealthy (which would spam) or every run
    while already healthy (which would be noise, not a notification).
    """
    if previously_healthy and not snapshot.is_healthy:
        return AlertAction.SEND_HEALTH_ALERT
    if not previously_healthy and snapshot.is_healthy:
        return AlertAction.SEND_RECOVERY_ALERT
    return AlertAction.NONE
