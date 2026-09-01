"""Tests the pure snapshot-assembly logic. fetch_db_stats is a thin
wrapper around persistence/signals_repo.py and is not exercised here —
consistent with live/run_once.py, which is also DB-touching and untested
against a live database in this suite.
"""

from datetime import UTC, datetime, timedelta

from goldsignal.analysis.diagnostics import build_snapshot, next_scheduled_scan
from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.strategy.scalp import ScalpStrategy

START = datetime(2026, 1, 1, tzinfo=UTC)


def test_next_scheduled_scan_rounds_up_to_interval():
    now = datetime(2026, 1, 1, 10, 7, 30, tzinfo=UTC)
    assert next_scheduled_scan(now, interval_minutes=15) == datetime(2026, 1, 1, 10, 15, tzinfo=UTC)


def test_next_scheduled_scan_rolls_into_next_hour():
    now = datetime(2026, 1, 1, 10, 59, tzinfo=UTC)
    assert next_scheduled_scan(now, interval_minutes=15) == datetime(2026, 1, 1, 11, 0, tzinfo=UTC)


def test_next_scheduled_scan_exactly_on_boundary_moves_to_next():
    now = datetime(2026, 1, 1, 10, 15, tzinfo=UTC)
    assert next_scheduled_scan(now, interval_minutes=15) == datetime(2026, 1, 1, 10, 30, tzinfo=UTC)


def _build():
    config = load_scalp_config({})
    strategy = ScalpStrategy(config, "XAUUSD")
    provider = MockDataProvider(seed=1)
    end = START + config.confirmation_timeframe.duration * 80
    entry = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)
    return strategy, entry, confirm, end


def test_build_snapshot_reports_feed_delay_and_session():
    strategy, entry, confirm, end = _build()
    now = end + timedelta(minutes=5)  # slightly after the data ends, like a real gap

    snapshot = build_snapshot(strategy, entry, confirm, instrument="XAUUSD", now=now)

    assert snapshot.latest_completed_candle == entry[-1].timestamp
    assert snapshot.feed_delay == now - (
        entry[-1].timestamp + strategy.config.entry_timeframe.duration
    )
    assert snapshot.current_session
    assert snapshot.stage
    assert snapshot.final_reason
    assert isinstance(snapshot.conditions, dict)


def test_build_snapshot_flags_staleness_when_data_far_behind():
    strategy, entry, confirm, end = _build()
    now = end + timedelta(hours=5)  # far beyond max staleness for M5

    snapshot = build_snapshot(strategy, entry, confirm, instrument="XAUUSD", now=now)
    assert snapshot.is_stale is True


def test_build_snapshot_handles_no_candles():
    strategy, _entry, confirm, end = _build()
    snapshot = build_snapshot(strategy, [], confirm, instrument="XAUUSD", now=end)
    assert snapshot.latest_completed_candle is None
    assert snapshot.feed_delay is None
