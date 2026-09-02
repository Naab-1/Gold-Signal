"""Durable, idempotent catch-up candle selection.

`iter_unprocessed_candles` is the one piece of the gap-tolerant scheduler
that decides *which* candles get evaluated on a given run and in what
order — deliberately kept pure (no I/O, no persistence) so gap scenarios
(10 minutes, 30 minutes, 4 hours, 24 hours of missed scans) can be
exercised in tests without a real database or clock.

Design:
  - A candle counts as "closed" only when its close time (`timestamp +
    entry_duration`) is at or before `now` — an in-progress candle is
    never evaluated.
  - With no checkpoint yet (this strategy/version/timeframe/provider has
    never been scanned), only the single most-recently-closed candle is
    yielded — matching today's live behavior on a fresh deployment,
    rather than flooding through however much lookback history happens
    to have been fetched.
  - With a checkpoint, every closed candle strictly after it is yielded,
    oldest first, so a caller can process them chronologically and
    advance the checkpoint one candle at a time.
  - Each yielded candle carries its own bounded lookback window (matching
    live/backtest's shared `_LOOKBACK_CANDLES` convention) and the
    confirmation-timeframe candles available as of its own close time —
    never a candle that hadn't closed yet relative to that entry candle,
    so catch-up processing can't accidentally look ahead.
  - `is_late` marks a candle whose close time is before the latest closed
    candle in the fetched series — i.e. discovered during a catch-up
    sweep rather than as the current, still-fresh candle.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from goldsignal.models.candle import Candle

DEFAULT_LOOKBACK_CANDLES = 300


@dataclass(frozen=True)
class UnprocessedCandle:
    close_time: datetime
    entry_window: list[Candle]
    confirmation_window: list[Candle]
    is_late: bool


def iter_unprocessed_candles(
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    *,
    entry_duration: timedelta,
    confirm_duration: timedelta,
    checkpoint: datetime | None,
    now: datetime,
    lookback_candles: int = DEFAULT_LOOKBACK_CANDLES,
) -> Iterator[UnprocessedCandle]:
    confirm_close_times = [c.timestamp + confirm_duration for c in confirmation_candles]

    closed = [(i, c) for i, c in enumerate(entry_candles) if (c.timestamp + entry_duration) <= now]
    if not closed:
        return

    if checkpoint is None:
        closed = closed[-1:]

    latest_close_time = closed[-1][1].timestamp + entry_duration

    for i, candle in closed:
        close_time = candle.timestamp + entry_duration
        if checkpoint is not None and close_time <= checkpoint:
            continue

        window_start = max(0, i + 1 - lookback_candles)
        window = entry_candles[window_start : i + 1]
        confirm_idx = bisect.bisect_right(confirm_close_times, close_time)
        confirm_window = confirmation_candles[:confirm_idx]

        yield UnprocessedCandle(
            close_time=close_time,
            entry_window=window,
            confirmation_window=confirm_window,
            is_late=close_time < latest_close_time,
        )
