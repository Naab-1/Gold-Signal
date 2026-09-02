"""Scheduler run log + health-alert transition state.

`scheduler_runs` is an append-only record of every invocation attempt
(started at the top of a run, finished — success or failure — at the
bottom), giving the monitoring numbers the spec asks for: last
invocation, last success, the gap between consecutive invocations. It is
deliberately separate from `scan_checkpoints` — a run can start, fail
before processing anything, and still be worth recording as "the
scheduler did fire," which is a different fact from "candles got
processed."

`scheduler_alert_state` exists only so the health/recovery Telegram
notices are transition-based (sent once when health flips, not once per
run) — see `live.health`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass(frozen=True)
class SchedulerRun:
    id: int
    started_at: datetime
    finished_at: datetime | None
    succeeded: bool | None
    candles_processed: int
    error_message: str | None


def record_run_start(
    conn: psycopg.Connection, *, strategy_mode: str, strategy_version: str, started_at: datetime
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scheduler_runs (strategy_mode, strategy_version, started_at)
            VALUES (%s, %s, %s) RETURNING id
            """,
            (strategy_mode, strategy_version, started_at),
        )
        (run_id,) = cur.fetchone()
    conn.commit()
    return run_id


def record_run_finish(
    conn: psycopg.Connection,
    run_id: int,
    *,
    finished_at: datetime,
    succeeded: bool,
    candles_processed: int,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE scheduler_runs
            SET finished_at = %s, succeeded = %s, candles_processed = %s, error_message = %s
            WHERE id = %s
            """,
            (finished_at, succeeded, candles_processed, error_message, run_id),
        )
    conn.commit()


def get_recent_runs(
    conn: psycopg.Connection, *, strategy_mode: str, strategy_version: str, limit: int = 5
) -> list[SchedulerRun]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, started_at, finished_at, succeeded, candles_processed, error_message
            FROM scheduler_runs
            WHERE strategy_mode = %s AND strategy_version = %s
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (strategy_mode, strategy_version, limit),
        )
        rows = cur.fetchall()
    return [
        SchedulerRun(
            id=r[0],
            started_at=r[1],
            finished_at=r[2],
            succeeded=r[3],
            candles_processed=r[4],
            error_message=r[5],
        )
        for r in rows
    ]


def get_last_successful_run_at(
    conn: psycopg.Connection, *, strategy_mode: str, strategy_version: str
) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT finished_at FROM scheduler_runs
            WHERE strategy_mode = %s AND strategy_version = %s AND succeeded = true
            ORDER BY finished_at DESC LIMIT 1
            """,
            (strategy_mode, strategy_version),
        )
        row = cur.fetchone()
    return row[0] if row else None


@dataclass(frozen=True)
class AlertState:
    is_healthy: bool
    unhealthy_since: datetime | None


def get_alert_state(
    conn: psycopg.Connection, *, strategy_mode: str, strategy_version: str
) -> AlertState:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT is_healthy, unhealthy_since FROM scheduler_alert_state
            WHERE strategy_mode = %s AND strategy_version = %s
            """,
            (strategy_mode, strategy_version),
        )
        row = cur.fetchone()
    if row is None:
        return AlertState(is_healthy=True, unhealthy_since=None)
    return AlertState(is_healthy=row[0], unhealthy_since=row[1])


def set_alert_state(
    conn: psycopg.Connection,
    *,
    strategy_mode: str,
    strategy_version: str,
    is_healthy: bool,
    unhealthy_since: datetime | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scheduler_alert_state (
                strategy_mode, strategy_version, is_healthy, unhealthy_since, updated_at
            ) VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (strategy_mode, strategy_version)
            DO UPDATE SET is_healthy = EXCLUDED.is_healthy,
                          unhealthy_since = EXCLUDED.unhealthy_since,
                          updated_at = now()
            """,
            (strategy_mode, strategy_version, is_healthy, unhealthy_since),
        )
    conn.commit()
