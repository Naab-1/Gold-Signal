"""Orchestration-level tests for the catch-up scan, using in-memory fakes
for the database-touching repo layers (same testing philosophy as the
rest of the persistence layer: pure/orchestration logic is unit-tested,
real psycopg calls are integration-only). Exercises the specific
guarantees from the spec that can't be checked by the pure `catchup`/
`actionability` tests alone:

  - every closed candle is evaluated exactly once across a real gap
  - a duplicate invocation (the same candle re-processed, checkpoint not
    yet advanced) does not send a second Telegram notification
  - a failure partway through a sweep leaves the checkpoint at the last
    successfully processed candle, not past the one that failed
  - a signal discovered too late to still be actionable is recorded as
    missed and alerted through the distinct "do not enter" path, never
    the live trade-alert path
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.live import run_once as run_once_module
from goldsignal.models.candle import Timeframe
from goldsignal.models.signal import (
    EntryOrderType,
    ProfitTarget,
    SignalDirection,
    StrategyMode,
    StrategySignal,
)
from goldsignal.persistence import signals_repo
from goldsignal.strategy.base import EvaluationContext

START = datetime(2026, 1, 1, tzinfo=UTC)


class FakeCheckpoints:
    def __init__(self):
        self.store: dict[tuple, datetime] = {}

    def get_checkpoint(self, conn, key):
        return self.store.get(key)

    def set_checkpoint(self, conn, key, candle_close):
        self.store[key] = candle_close


class FakeSignalsRepo:
    """Mirrors the real repo's idempotency contract in memory: `save_signal`
    is ON-CONFLICT-DO-NOTHING by signal_id, `claim_telegram_send` only
    succeeds once per signal_id.
    """

    def __init__(self, *, fail_on_signal_id: str | None = None):
        self.rows: dict[str, dict] = {}
        self.fail_on_signal_id = fail_on_signal_id
        self.telegram_send_attempts: list[str] = []

    def save_signal(self, conn, signal, *, detected_late=False):
        if signal.signal_id == self.fail_on_signal_id:
            raise RuntimeError("simulated persistence failure")
        self.rows.setdefault(
            signal.signal_id,
            {
                "signal": signal,
                "detected_late": detected_late,
                "telegram_sent": False,
                "missed": None,
            },
        )

    # Delegate the pure functions to the real module so dedup/fingerprint
    # logic under test is the actual production logic, not a re-implementation.
    fingerprint_of = staticmethod(signals_repo.fingerprint_of)
    is_duplicate = staticmethod(signals_repo.is_duplicate)

    def get_last_trade_signal(self, conn, *, strategy_mode, instrument):
        return None  # no prior actionable signal in these tests

    def claim_telegram_send(self, conn, signal_id):
        self.telegram_send_attempts.append(signal_id)
        row = self.rows[signal_id]
        if row["telegram_sent"]:
            return False
        row["telegram_sent"] = True
        return True

    def unclaim_telegram_send(self, conn, signal_id):
        self.rows[signal_id]["telegram_sent"] = False

    def mark_missed(self, conn, signal_id, *, reason):
        self.rows[signal_id]["missed"] = reason

    def build_evaluation_context(self, conn, *, strategy_mode, instrument, now):
        return EvaluationContext()

    def count_missed_since(self, conn, *, strategy_mode, instrument, since):
        return sum(1 for r in self.rows.values() if r["missed"] is not None)


class ScriptedStrategy:
    mode = StrategyMode.SCALP
    version = "test_v1"

    def __init__(self, config, instrument, signals_by_close_time: dict[datetime, StrategySignal]):
        self.config = config
        self.instrument = instrument
        self._signals_by_close_time = signals_by_close_time
        self.evaluate_calls: list[datetime] = []

    def evaluate(self, entry_candles, confirmation_candles, *, now, context=None):
        self.evaluate_calls.append(now)
        if now in self._signals_by_close_time:
            return self._signals_by_close_time[now]
        return _no_trade_at(now)


def _no_trade_at(close_time: datetime) -> StrategySignal:
    return StrategySignal(
        signal_id=f"no_trade:{close_time.isoformat()}",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="test_v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.NO_TRADE,
        signal_timestamp=close_time,
        entry_price=None,
        entry_order_type=None,
        stop_loss=None,
        targets=[],
        setup_expiration=None,
        invalidation_conditions=[],
        estimated_spread=None,
        estimated_slippage=None,
    )


def _buy_signal_at(
    close_time: datetime, *, entry=2450.0, stop=2445.0, expiration_minutes=30, signal_id=None
) -> StrategySignal:
    return StrategySignal(
        signal_id=signal_id or f"buy:{close_time.isoformat()}",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="test_v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.BUY,
        signal_timestamp=close_time,
        entry_price=entry,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=stop,
        targets=[ProfitTarget(label="TP1", price=2460.0, r_multiple=2.0)],
        setup_expiration=close_time + timedelta(minutes=expiration_minutes),
        invalidation_conditions=[],
        estimated_spread=0.3,
        estimated_slippage=0.2,
    )


@pytest.fixture(autouse=True)
def _mock_telegram(monkeypatch):
    sent = {"trade": [], "missed": []}
    monkeypatch.setattr(
        run_once_module, "send_signal_alert", lambda signal, **kw: sent["trade"].append(signal)
    )
    monkeypatch.setattr(
        run_once_module,
        "send_missed_setup_alert",
        lambda signal, **kw: sent["missed"].append(signal),
    )
    return sent


def _settings():
    from goldsignal.config import GlobalSettings

    return GlobalSettings(
        data_provider="mock",
        instrument="XAUUSD",
        log_level="INFO",
        twelvedata_api_key=None,
        telegram_bot_token="TOKEN",
        telegram_chat_id="CHAT",
        telegram_debug_mode=False,
        database_url=None,
    )


def _candles(config, n=400):
    provider = MockDataProvider(seed=1, base_price=2450.0, volatility=1.0)
    end = START + config.entry_timeframe.duration * n
    entry = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)
    return entry, confirm


def test_every_closed_candle_across_a_4_hour_gap_is_evaluated_exactly_once(monkeypatch):
    config = load_scalp_config({})
    entry, confirm = _candles(config)
    strategy = ScriptedStrategy(config, "XAUUSD", {})
    fake_checkpoints = FakeCheckpoints()
    fake_signals = FakeSignalsRepo()
    monkeypatch.setattr(run_once_module, "checkpoints_repo", fake_checkpoints)
    monkeypatch.setattr(run_once_module, "signals_repo", fake_signals)

    settings = _settings()
    key = run_once_module._checkpoint_key(settings, config, strategy)
    now = entry[100].timestamp + config.entry_timeframe.duration
    fake_checkpoints.store[key] = now  # simulate an already-caught-up state

    gap_now = now + timedelta(hours=4)

    class FixedProvider:
        def get_candles(self, instrument, timeframe, start, end):
            return entry if timeframe == config.entry_timeframe else confirm

    processed = run_once_module._run_catchup(
        conn=None,
        settings=settings,
        config=config,
        strategy=strategy,
        provider=FixedProvider(),
        wall_clock_now=gap_now,
    )

    expected = int(timedelta(hours=4) / config.entry_timeframe.duration)
    assert processed == expected
    assert len(strategy.evaluate_calls) == expected
    assert len(set(strategy.evaluate_calls)) == expected  # no repeats
    assert strategy.evaluate_calls == sorted(strategy.evaluate_calls)  # chronological


def test_duplicate_invocation_sends_exactly_one_alert(monkeypatch, _mock_telegram):
    # This test is about idempotent-send infrastructure, not strategy
    # validation, so it explicitly opts into actionable alerts -- the
    # config default is now False (see docs/baseline_rejection.md).
    config = load_scalp_config({"GOLDSIGNAL_SCALP_ACTIONABLE_ALERTS_ENABLED": "true"})
    entry, confirm = _candles(config)
    signal_close_time = entry[50].timestamp + config.entry_timeframe.duration
    buy_signal = _buy_signal_at(signal_close_time)
    strategy = ScriptedStrategy(config, "XAUUSD", {signal_close_time: buy_signal})

    fake_checkpoints = FakeCheckpoints()
    fake_signals = FakeSignalsRepo()
    monkeypatch.setattr(run_once_module, "checkpoints_repo", fake_checkpoints)
    monkeypatch.setattr(run_once_module, "signals_repo", fake_signals)

    settings = _settings()
    key = run_once_module._checkpoint_key(settings, config, strategy)

    class FixedProvider:
        def get_candles(self, instrument, timeframe, start, end):
            return entry if timeframe == config.entry_timeframe else confirm

    for _ in range(2):
        fake_checkpoints.store[key] = signal_close_time - config.entry_timeframe.duration
        run_once_module._run_catchup(
            conn=None,
            settings=settings,
            config=config,
            strategy=strategy,
            provider=FixedProvider(),
            wall_clock_now=signal_close_time,
        )

    assert len(_mock_telegram["trade"]) == 1
    assert fake_signals.telegram_send_attempts == [buy_signal.signal_id, buy_signal.signal_id]


def test_checkpoint_is_not_advanced_past_a_candle_that_fails_to_process(monkeypatch):
    config = load_scalp_config({})
    entry, confirm = _candles(config)
    strategy = ScriptedStrategy(config, "XAUUSD", {})

    fail_close_time = entry[53].timestamp + config.entry_timeframe.duration
    fake_checkpoints = FakeCheckpoints()
    fake_signals = FakeSignalsRepo(fail_on_signal_id=f"no_trade:{fail_close_time.isoformat()}")
    monkeypatch.setattr(run_once_module, "checkpoints_repo", fake_checkpoints)
    monkeypatch.setattr(run_once_module, "signals_repo", fake_signals)

    settings = _settings()
    key = run_once_module._checkpoint_key(settings, config, strategy)
    start_checkpoint = entry[50].timestamp + config.entry_timeframe.duration
    fake_checkpoints.store[key] = start_checkpoint
    now = entry[60].timestamp + config.entry_timeframe.duration

    class FixedProvider:
        def get_candles(self, instrument, timeframe, start, end):
            return entry if timeframe == config.entry_timeframe else confirm

    processed = run_once_module._run_catchup(
        conn=None,
        settings=settings,
        config=config,
        strategy=strategy,
        provider=FixedProvider(),
        wall_clock_now=now,
    )

    # Candles at start_checkpoint+1 .. fail_close_time-1 succeed, the one
    # AT fail_close_time fails and processing stops there.
    expected_successful = (
        int((fail_close_time - start_checkpoint) / config.entry_timeframe.duration) - 1
    )
    assert processed == expected_successful
    assert fake_checkpoints.store[key] == fail_close_time - config.entry_timeframe.duration
    assert fake_checkpoints.store[key] != fail_close_time


def test_signal_no_longer_actionable_is_marked_missed_not_sent_live(monkeypatch, _mock_telegram):
    config = load_scalp_config({})
    entry, confirm = _candles(config)

    # A setup whose expiration has already passed relative to wall-clock
    # "now" -- discovered during a catch-up sweep, too late to act on.
    signal_close_time = entry[50].timestamp + config.entry_timeframe.duration
    expired_signal = _buy_signal_at(signal_close_time, expiration_minutes=5)
    strategy = ScriptedStrategy(config, "XAUUSD", {signal_close_time: expired_signal})

    fake_checkpoints = FakeCheckpoints()
    fake_signals = FakeSignalsRepo()
    monkeypatch.setattr(run_once_module, "checkpoints_repo", fake_checkpoints)
    monkeypatch.setattr(run_once_module, "signals_repo", fake_signals)

    settings = _settings()
    key = run_once_module._checkpoint_key(settings, config, strategy)
    fake_checkpoints.store[key] = signal_close_time - config.entry_timeframe.duration
    wall_clock_now = signal_close_time + timedelta(hours=4)  # long after expiration

    class FixedProvider:
        def get_candles(self, instrument, timeframe, start, end):
            return entry if timeframe == config.entry_timeframe else confirm

    run_once_module._run_catchup(
        conn=None,
        settings=settings,
        config=config,
        strategy=strategy,
        provider=FixedProvider(),
        wall_clock_now=wall_clock_now,
    )

    assert fake_signals.rows[expired_signal.signal_id]["missed"] is not None
    assert fake_signals.rows[expired_signal.signal_id]["telegram_sent"] is False
    assert len(_mock_telegram["trade"]) == 0
    assert len(_mock_telegram["missed"]) == 1


def test_actionable_alert_suppressed_by_default_but_still_recorded(monkeypatch, _mock_telegram):
    """Phase 1 safety freeze: with the default config (actionable_alerts_enabled
    is False for an unvalidated baseline), a real, still-actionable BUY signal
    must be saved and dedup/actionability-checked as normal, but must never
    reach send_signal_alert.
    """
    config = load_scalp_config({})  # default: actionable_alerts_enabled=False
    entry, confirm = _candles(config)
    signal_close_time = entry[50].timestamp + config.entry_timeframe.duration
    buy_signal = _buy_signal_at(signal_close_time)
    strategy = ScriptedStrategy(config, "XAUUSD", {signal_close_time: buy_signal})

    fake_checkpoints = FakeCheckpoints()
    fake_signals = FakeSignalsRepo()
    monkeypatch.setattr(run_once_module, "checkpoints_repo", fake_checkpoints)
    monkeypatch.setattr(run_once_module, "signals_repo", fake_signals)

    settings = _settings()
    key = run_once_module._checkpoint_key(settings, config, strategy)
    fake_checkpoints.store[key] = signal_close_time - config.entry_timeframe.duration

    class FixedProvider:
        def get_candles(self, instrument, timeframe, start, end):
            return entry if timeframe == config.entry_timeframe else confirm

    run_once_module._run_catchup(
        conn=None,
        settings=settings,
        config=config,
        strategy=strategy,
        provider=FixedProvider(),
        wall_clock_now=signal_close_time,
    )

    assert buy_signal.signal_id in fake_signals.rows  # still recorded
    assert fake_signals.rows[buy_signal.signal_id]["telegram_sent"] is False
    assert len(_mock_telegram["trade"]) == 0
    assert len(_mock_telegram["missed"]) == 0  # not "missed" either -- suppressed, not late


def test_skips_fetch_entirely_when_no_new_candle_could_have_closed(monkeypatch):
    """Root cause of a real production incident: polling every 5 minutes
    while always fetching fresh candle data, even when nothing new could
    possibly have closed yet, burned through TwelveData's daily free-tier
    quota and caused persistent HTTP 429 failures. This proves the fetch
    is skipped entirely (not just fast) whenever the checkpoint already
    covers the present moment.
    """
    config = load_scalp_config({})
    strategy = ScriptedStrategy(config, "XAUUSD", {})

    fake_checkpoints = FakeCheckpoints()
    fake_signals = FakeSignalsRepo()
    monkeypatch.setattr(run_once_module, "checkpoints_repo", fake_checkpoints)
    monkeypatch.setattr(run_once_module, "signals_repo", fake_signals)

    settings = _settings()
    key = run_once_module._checkpoint_key(settings, config, strategy)
    now = START
    # Checkpoint already covers "now" -- the next candle can't close for
    # another 5 minutes, so there's nothing to fetch.
    fake_checkpoints.store[key] = now

    class ProviderThatMustNotBeCalled:
        def get_candles(self, instrument, timeframe, start, end):
            raise AssertionError("get_candles should not be called when nothing new can exist")

    processed = run_once_module._run_catchup(
        conn=None,
        settings=settings,
        config=config,
        strategy=strategy,
        provider=ProviderThatMustNotBeCalled(),
        wall_clock_now=now + timedelta(minutes=1),  # < one entry_timeframe duration later
    )

    assert processed == 0


def test_does_not_skip_once_a_new_candle_could_have_closed(monkeypatch):
    config = load_scalp_config({})
    entry, confirm = _candles(config)
    strategy = ScriptedStrategy(config, "XAUUSD", {})

    fake_checkpoints = FakeCheckpoints()
    fake_signals = FakeSignalsRepo()
    monkeypatch.setattr(run_once_module, "checkpoints_repo", fake_checkpoints)
    monkeypatch.setattr(run_once_module, "signals_repo", fake_signals)

    settings = _settings()
    key = run_once_module._checkpoint_key(settings, config, strategy)
    checkpoint = entry[50].timestamp + config.entry_timeframe.duration
    fake_checkpoints.store[key] = checkpoint

    class FixedProvider:
        def get_candles(self, instrument, timeframe, start, end):
            return entry if timeframe == config.entry_timeframe else confirm

    processed = run_once_module._run_catchup(
        conn=None,
        settings=settings,
        config=config,
        strategy=strategy,
        provider=FixedProvider(),
        wall_clock_now=checkpoint + config.entry_timeframe.duration,  # exactly one candle later
    )

    assert processed == 1
