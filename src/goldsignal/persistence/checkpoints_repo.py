"""Per-(strategy, version, timeframe, provider, instrument) catch-up
checkpoint: the close timestamp of the last closed candle that was fully
and successfully processed. Advancing this only happens after a candle's
evaluation, persistence, and (if actionable) alerting all succeeded —
callers must not call `set_checkpoint` on a failed candle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg


@dataclass(frozen=True)
class CheckpointKey:
    strategy_mode: str
    strategy_version: str
    entry_timeframe: str
    data_provider: str
    instrument: str


def get_checkpoint(conn: psycopg.Connection, key: CheckpointKey) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT last_processed_candle_close FROM scan_checkpoints
            WHERE strategy_mode = %s AND strategy_version = %s AND entry_timeframe = %s
              AND data_provider = %s AND instrument = %s
            """,
            (
                key.strategy_mode,
                key.strategy_version,
                key.entry_timeframe,
                key.data_provider,
                key.instrument,
            ),
        )
        row = cur.fetchone()
    return row[0] if row else None


def set_checkpoint(conn: psycopg.Connection, key: CheckpointKey, candle_close: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scan_checkpoints (
                strategy_mode, strategy_version, entry_timeframe, data_provider,
                instrument, last_processed_candle_close, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (
                strategy_mode, strategy_version, entry_timeframe, data_provider, instrument
            )
            DO UPDATE SET last_processed_candle_close = EXCLUDED.last_processed_candle_close,
                          updated_at = now()
            """,
            (
                key.strategy_mode,
                key.strategy_version,
                key.entry_timeframe,
                key.data_provider,
                key.instrument,
                candle_close,
            ),
        )
    conn.commit()
