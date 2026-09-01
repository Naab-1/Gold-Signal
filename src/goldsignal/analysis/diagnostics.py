"""Live signal-diagnostics snapshot: latest completed candle, feed delay,
current session, a fresh rule-by-rule evaluation right now, and (when a DB
connection is supplied) history counts.

The pure snapshot-assembly logic (`build_snapshot`) takes already-fetched
data and is fully unit-testable. `fetch_db_stats` is a thin DB-touching
wrapper around persistence/signals_repo.py, not unit tested against a
live database — consistent with live/run_once.py, which is also
DB-touching and also untested against real Postgres in this suite.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta

from goldsignal.data.validation import validate_candles
from goldsignal.models.candle import Candle
from goldsignal.notifications.sessions import session_label
from goldsignal.strategy._common import evaluate_with_trace
from goldsignal.strategy.base import EvaluationContext, Strategy

_DEFAULT_SCAN_INTERVAL_MINUTES = 15


@dataclasses.dataclass
class DbStats:
    latest_scan_timestamp: datetime | None
    signals_last_24h: int
    signals_last_7d: int
    signals_last_30d: int
    consecutive_no_signal_scans: int


@dataclasses.dataclass
class DiagnosticsSnapshot:
    mode: str
    now: datetime
    latest_completed_candle: datetime | None
    feed_delay: timedelta | None
    is_stale: bool
    current_session: str
    next_scheduled_scan: datetime
    conditions: dict[str, bool]
    stage: str
    final_reason: str
    near_miss_condition: str | None
    db_stats: DbStats | None = None


def next_scheduled_scan(
    now: datetime, *, interval_minutes: int = _DEFAULT_SCAN_INTERVAL_MINUTES
) -> datetime:
    """Assumes the standard `*/N * * * *` cron schedule used by
    .github/workflows/check-signals.yml — this is an estimate, not a query
    against GitHub's actual scheduler state.
    """
    base = now.replace(second=0, microsecond=0)
    next_minute = (base.minute // interval_minutes + 1) * interval_minutes
    if next_minute >= 60:
        return base.replace(minute=0) + timedelta(hours=next_minute // 60)
    return base.replace(minute=next_minute)


def build_snapshot(
    strategy: Strategy,
    entry_candles_raw: list[Candle],
    confirmation_candles_raw: list[Candle],
    *,
    instrument: str,
    now: datetime,
    context: EvaluationContext | None = None,
    db_stats: DbStats | None = None,
) -> DiagnosticsSnapshot:
    config = strategy.config
    entry_result = validate_candles(entry_candles_raw, config.entry_timeframe, now)
    confirm_result = validate_candles(confirmation_candles_raw, config.confirmation_timeframe, now)

    latest_completed_candle = (
        entry_result.clean_candles[-1].timestamp if entry_result.clean_candles else None
    )
    feed_delay = (
        now - (latest_completed_candle + config.entry_timeframe.duration)
        if latest_completed_candle
        else None
    )

    signal, trace = evaluate_with_trace(
        mode=strategy.mode,
        version=strategy.version,
        config=config,
        instrument=instrument,
        entry_candles=entry_result.clean_candles,
        confirmation_candles=confirm_result.clean_candles,
        now=now,
        context=context,
    )

    near_miss_condition = None
    if trace.conditions:
        failed = [name for name, ok in trace.conditions.items() if not ok]
        if len(failed) == 1:
            near_miss_condition = failed[0]

    return DiagnosticsSnapshot(
        mode=strategy.mode.value,
        now=now,
        latest_completed_candle=latest_completed_candle,
        feed_delay=feed_delay,
        is_stale=entry_result.is_stale,
        current_session=session_label(now),
        next_scheduled_scan=next_scheduled_scan(now),
        conditions=trace.conditions,
        stage=trace.stage,
        final_reason=signal.reason,
        near_miss_condition=near_miss_condition,
        db_stats=db_stats,
    )


def fetch_db_stats(conn, *, strategy_mode: str, instrument: str, now: datetime) -> DbStats:
    from goldsignal.persistence import signals_repo

    return DbStats(
        latest_scan_timestamp=signals_repo.get_latest_signal_timestamp(
            conn, strategy_mode=strategy_mode, instrument=instrument
        ),
        signals_last_24h=signals_repo.count_signals_since(
            conn,
            strategy_mode=strategy_mode,
            instrument=instrument,
            since=now - timedelta(hours=24),
        ),
        signals_last_7d=signals_repo.count_signals_since(
            conn, strategy_mode=strategy_mode, instrument=instrument, since=now - timedelta(days=7)
        ),
        signals_last_30d=signals_repo.count_signals_since(
            conn, strategy_mode=strategy_mode, instrument=instrument, since=now - timedelta(days=30)
        ),
        consecutive_no_signal_scans=signals_repo.count_consecutive_no_trade_scans(
            conn, strategy_mode=strategy_mode, instrument=instrument
        ),
    )
