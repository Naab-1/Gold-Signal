"""Signal journal repository: persistence + dedup/cooldown-context logic.

The dedup/fingerprint logic is pure Python, fully unit-testable without a
live database. Only the thin `save_signal`/`get_last_trade_signal`/
`count_signals_today` functions touch psycopg, and they're exercised for
real only via `live/run_once.py` against the user's own Neon instance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

from goldsignal.models.signal import SignalDirection, StrategySignal
from goldsignal.strategy.base import EvaluationContext


@dataclass(frozen=True)
class SignalFingerprint:
    direction: str
    stop_loss: float | None
    target_prices: tuple[float, ...]


@dataclass(frozen=True)
class LastSignalRecord:
    fingerprint: SignalFingerprint
    signal_timestamp: datetime


def fingerprint_of(signal: StrategySignal) -> SignalFingerprint:
    return SignalFingerprint(
        direction=signal.direction.value,
        stop_loss=signal.stop_loss,
        target_prices=tuple(t.price for t in signal.targets),
    )


def is_duplicate(new: SignalFingerprint, last: LastSignalRecord | None) -> bool:
    """True if `new` represents the same trade idea as the last stored
    signal for this mode/instrument (same direction, stop, and target
    prices) — entry price is allowed to drift candle to candle without
    counting as a new idea. NO_TRADE is never considered a duplicate.
    """
    if last is None or new.direction == SignalDirection.NO_TRADE.value:
        return False
    return (
        new.direction == last.fingerprint.direction
        and new.stop_loss == last.fingerprint.stop_loss
        and new.target_prices == last.fingerprint.target_prices
    )


def save_signal(conn: psycopg.Connection, signal: StrategySignal) -> None:
    targets_json = json.dumps(
        [{"label": t.label, "price": t.price, "r_multiple": t.r_multiple} for t in signal.targets]
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO signals (
                signal_id, instrument, strategy_mode, strategy_version, direction,
                entry_timeframe, confirmation_timeframe, signal_timestamp,
                entry_price, stop_loss, targets_json, confidence_score, reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (signal_id) DO NOTHING
            """,
            (
                signal.signal_id,
                signal.instrument,
                signal.strategy_mode.value,
                signal.strategy_version,
                signal.direction.value,
                signal.entry_timeframe.value,
                signal.confirmation_timeframe.value,
                signal.signal_timestamp,
                signal.entry_price,
                signal.stop_loss,
                targets_json,
                signal.confidence_score,
                signal.reason,
            ),
        )
    conn.commit()


def get_last_trade_signal(
    conn: psycopg.Connection, *, strategy_mode: str, instrument: str
) -> LastSignalRecord | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT direction, stop_loss, targets_json, signal_timestamp
            FROM signals
            WHERE strategy_mode = %s AND instrument = %s AND direction != 'NO_TRADE'
            ORDER BY signal_timestamp DESC
            LIMIT 1
            """,
            (strategy_mode, instrument),
        )
        row = cur.fetchone()
    if row is None:
        return None
    direction, stop_loss, targets_json, signal_timestamp = row
    target_prices = tuple(t["price"] for t in json.loads(targets_json))
    return LastSignalRecord(
        fingerprint=SignalFingerprint(
            direction=direction, stop_loss=stop_loss, target_prices=target_prices
        ),
        signal_timestamp=signal_timestamp,
    )


def count_signals_today(
    conn: psycopg.Connection, *, strategy_mode: str, instrument: str, now: datetime
) -> int:
    day_start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM signals
            WHERE strategy_mode = %s AND instrument = %s
              AND direction != 'NO_TRADE' AND signal_timestamp >= %s
            """,
            (strategy_mode, instrument, day_start),
        )
        (count,) = cur.fetchone()
    return count


def build_evaluation_context(
    conn: psycopg.Connection, *, strategy_mode: str, instrument: str, now: datetime
) -> EvaluationContext:
    last = get_last_trade_signal(conn, strategy_mode=strategy_mode, instrument=instrument)
    return EvaluationContext(
        last_signal_time=last.signal_timestamp if last else None,
        signals_emitted_this_session=count_signals_today(
            conn, strategy_mode=strategy_mode, instrument=instrument, now=now
        ),
    )
