"""Pure scheduler-health evaluation and alert-transition tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from goldsignal.live.health import (
    UNHEALTHY_AFTER,
    AlertAction,
    decide_alert_action,
    evaluate_health,
)

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
M5 = timedelta(minutes=5)


def test_healthy_when_last_success_within_two_expected_intervals():
    snap = evaluate_health(
        strategy_mode="SCALP",
        now=NOW,
        last_successful_run_at=NOW - UNHEALTHY_AFTER + timedelta(seconds=1),
        last_processed_candle=NOW - M5,
        expected_latest_closed_candle=NOW - M5,
        entry_duration=M5,
    )
    assert snap.is_healthy is True


def test_unhealthy_once_two_expected_intervals_are_missed():
    snap = evaluate_health(
        strategy_mode="SCALP",
        now=NOW,
        last_successful_run_at=NOW - UNHEALTHY_AFTER - timedelta(seconds=1),
        last_processed_candle=NOW - timedelta(minutes=15),
        expected_latest_closed_candle=NOW - M5,
        entry_duration=M5,
    )
    assert snap.is_healthy is False
    assert snap.gap_since_last_success > UNHEALTHY_AFTER


def test_never_run_before_is_treated_as_healthy_not_a_false_alarm():
    snap = evaluate_health(
        strategy_mode="SCALP",
        now=NOW,
        last_successful_run_at=None,
        last_processed_candle=None,
        expected_latest_closed_candle=NOW - M5,
        entry_duration=M5,
    )
    assert snap.is_healthy is True
    assert snap.gap_since_last_success is None


def test_unprocessed_candle_count_reflects_the_backlog():
    snap = evaluate_health(
        strategy_mode="SCALP",
        now=NOW,
        last_successful_run_at=NOW,
        last_processed_candle=NOW - timedelta(minutes=20),
        expected_latest_closed_candle=NOW,
        entry_duration=M5,
    )
    assert snap.unprocessed_candle_count == 4


def test_up_to_date_checkpoint_has_zero_backlog():
    snap = evaluate_health(
        strategy_mode="SCALP",
        now=NOW,
        last_successful_run_at=NOW,
        last_processed_candle=NOW,
        expected_latest_closed_candle=NOW,
        entry_duration=M5,
    )
    assert snap.unprocessed_candle_count == 0


def test_alert_fires_only_on_healthy_to_unhealthy_transition():
    unhealthy_snap = evaluate_health(
        strategy_mode="SCALP",
        now=NOW,
        last_successful_run_at=NOW - UNHEALTHY_AFTER - timedelta(minutes=1),
        last_processed_candle=None,
        expected_latest_closed_candle=None,
        entry_duration=M5,
    )
    assert (
        decide_alert_action(unhealthy_snap, previously_healthy=True)
        == AlertAction.SEND_HEALTH_ALERT
    )
    # Already unhealthy last time -- must not fire again (no spam every run).
    assert decide_alert_action(unhealthy_snap, previously_healthy=False) == AlertAction.NONE


def test_recovery_alert_fires_only_on_unhealthy_to_healthy_transition():
    healthy_snap = evaluate_health(
        strategy_mode="SCALP",
        now=NOW,
        last_successful_run_at=NOW,
        last_processed_candle=NOW,
        expected_latest_closed_candle=NOW,
        entry_duration=M5,
    )
    assert (
        decide_alert_action(healthy_snap, previously_healthy=False)
        == AlertAction.SEND_RECOVERY_ALERT
    )
    # Already healthy -- must not send a recovery notice every run.
    assert decide_alert_action(healthy_snap, previously_healthy=True) == AlertAction.NONE
