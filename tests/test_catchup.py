"""Pure catch-up candle-selection tests — no database, no clock, no
network. Directly exercises the gap scenarios from the spec (10 minutes,
30 minutes, 4 hours, 24 hours) plus the invariants around them: every
closed candle evaluated exactly once, chronological order, no lookahead,
and a duplicate invocation (unchanged checkpoint) finding nothing new.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from goldsignal.live.catchup import iter_unprocessed_candles
from goldsignal.models.candle import Candle

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
M5 = timedelta(minutes=5)
M15 = timedelta(minutes=15)


def _entry_candles(n: int, *, start: datetime = START) -> list[Candle]:
    return [
        Candle(
            timestamp=start + i * M5,
            open=2450.0 + i,
            high=2451.0 + i,
            low=2449.0 + i,
            close=2450.5 + i,
            volume=1.0,
        )
        for i in range(n)
    ]


def _confirm_candles(n: int, *, start: datetime = START) -> list[Candle]:
    return [
        Candle(
            timestamp=start + i * M15,
            open=2450.0,
            high=2452.0,
            low=2448.0,
            close=2451.0,
            volume=1.0,
        )
        for i in range(n)
    ]


def _run(entry, confirm, *, checkpoint, now):
    return list(
        iter_unprocessed_candles(
            entry,
            confirm,
            entry_duration=M5,
            confirm_duration=M15,
            checkpoint=checkpoint,
            now=now,
        )
    )


def test_no_checkpoint_processes_only_the_single_latest_closed_candle():
    entry = _entry_candles(50)
    confirm = _confirm_candles(20)
    now = entry[-1].timestamp + M5  # exactly when the last candle closes
    result = _run(entry, confirm, checkpoint=None, now=now)
    assert len(result) == 1
    assert result[0].close_time == now
    assert result[0].is_late is False


def test_still_forming_candle_is_never_yielded():
    entry = _entry_candles(10)
    confirm = _confirm_candles(5)
    # `now` is mid-way through the last candle's period -> it hasn't closed.
    now = entry[-1].timestamp + timedelta(minutes=2)
    result = _run(entry, confirm, checkpoint=None, now=now)
    assert len(result) == 1
    assert result[0].close_time == entry[-2].timestamp + M5  # the previous, actually-closed one


def _gap_scenario(gap: timedelta):
    """Build a checkpoint at some closed candle, then `gap` worth of newly
    closed candles after it, and assert the catch-up sweep finds exactly
    those candles, in order, each marked late except the very last.
    """
    total_candles = int(gap / M5) + 20
    entry = _entry_candles(total_candles)
    confirm = _confirm_candles(total_candles // 3 + 5, start=START)

    checkpoint_index = 10
    checkpoint = entry[checkpoint_index].timestamp + M5
    now = checkpoint + gap

    result = _run(entry, confirm, checkpoint=checkpoint, now=now)

    expected_count = int(gap / M5)
    assert len(result) == expected_count

    expected_close_times = [checkpoint + (i + 1) * M5 for i in range(expected_count)]
    assert [r.close_time for r in result] == expected_close_times

    # Every candle here closed strictly before `now` and strictly after
    # the checkpoint -- none skipped, none repeated, none still-forming.
    for r in result:
        assert checkpoint < r.close_time <= now

    # All but the very last are "late" (discovered during the sweep,
    # not as the current freshest candle).
    assert all(r.is_late for r in result[:-1])
    assert result[-1].is_late is False
    return result


def test_gap_of_10_minutes_is_fully_caught_up():
    _gap_scenario(timedelta(minutes=10))


def test_gap_of_30_minutes_is_fully_caught_up():
    _gap_scenario(timedelta(minutes=30))


def test_gap_of_4_hours_is_fully_caught_up():
    _gap_scenario(timedelta(hours=4))


def test_gap_of_24_hours_is_fully_caught_up():
    _gap_scenario(timedelta(hours=24))


def test_duplicate_invocation_with_unchanged_checkpoint_finds_nothing_new():
    entry = _entry_candles(60)
    confirm = _confirm_candles(20)
    now = entry[-1].timestamp + M5
    checkpoint = now  # as if a previous run already processed through `now`

    result = _run(entry, confirm, checkpoint=checkpoint, now=now)
    assert result == []


def test_resuming_after_a_processed_prefix_only_yields_the_remainder():
    entry = _entry_candles(100)
    confirm = _confirm_candles(35)
    now = entry[-1].timestamp + M5

    first_pass = _run(entry, confirm, checkpoint=None, now=now - 20 * M5)
    assert len(first_pass) == 1
    checkpoint_after_first = first_pass[0].close_time

    second_pass = _run(entry, confirm, checkpoint=checkpoint_after_first, now=now)
    assert len(second_pass) == 20
    assert second_pass[0].close_time == checkpoint_after_first + M5
    assert second_pass[-1].close_time == now


def test_entry_window_is_bounded_to_lookback_candles():
    entry = _entry_candles(500)
    confirm = _confirm_candles(50)
    now = entry[-1].timestamp + M5
    checkpoint = entry[-2].timestamp + M5  # only the very last candle is new

    result = _run(entry, confirm, checkpoint=checkpoint, now=now)
    assert len(result) == 1
    assert len(result[0].entry_window) == 300  # DEFAULT_LOOKBACK_CANDLES, not all 500
    assert result[0].entry_window[-1].timestamp == entry[-1].timestamp


def test_confirmation_window_never_includes_a_not_yet_closed_confirmation_candle():
    entry = _entry_candles(10)
    confirm = _confirm_candles(3)  # closes at START+15m, +30m, +45m
    checkpoint = entry[2].timestamp + M5  # = START + 15m
    now = entry[5].timestamp + M5  # = START + 30m

    result = _run(entry, confirm, checkpoint=checkpoint, now=now)
    # For the candle closing at START+20m, only the confirmation candle
    # that closed at START+15m should be visible -- not the one at +30m,
    # which hadn't closed yet relative to that entry candle.
    first = result[0]
    assert first.close_time == START + timedelta(minutes=20)
    assert [c.timestamp for c in first.confirmation_window] == [START]
