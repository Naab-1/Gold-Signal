from datetime import UTC, datetime

import pytest

from goldsignal.backtest.final_oos_ledger import (
    FinalOosAlreadyEvaluatedError,
    FinalOosEvaluation,
    assert_not_yet_evaluated,
    has_been_evaluated,
    record_evaluation,
)
from goldsignal.backtest.metrics import compute_summary
from goldsignal.backtest.models import BacktestTrade
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.trade_management import TradeManagementPreset

START = datetime(2026, 1, 1, tzinfo=UTC)


def _trade(realized_r=0.5):
    return BacktestTrade(
        signal_id="s",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="trend_pullback_v1",
        trade_management_preset=TradeManagementPreset.BALANCED,
        direction=SignalDirection.BUY,
        signal_timestamp=START,
        fill_timestamp=START,
        fill_price=100.0,
        initial_stop_loss=95.0,
        risk=5.0,
        realized_r=realized_r,
    )


def _summary():
    return compute_summary(
        [_trade(0.5), _trade(-1.0)],
        strategy_mode=StrategyMode.SCALP,
        preset=TradeManagementPreset.BALANCED,
        split_label="final_out_of_sample",
    )


def _evaluation(**overrides):
    defaults = dict(
        strategy_version="trend_pullback_v1",
        instrument="XAUUSD",
        mode="scalp",
        evaluated_at=START,
        summary=_summary(),
        dataset_note="2yr, TwelveData",
    )
    defaults.update(overrides)
    return FinalOosEvaluation(**defaults)


def test_has_not_been_evaluated_when_ledger_file_does_not_exist(tmp_path):
    ledger_path = tmp_path / "final_oos.jsonl"
    assert (
        has_been_evaluated(ledger_path, strategy_version="v1", instrument="XAUUSD", mode="scalp")
        is False
    )


def test_has_not_been_evaluated_when_key_does_not_match(tmp_path):
    ledger_path = tmp_path / "final_oos.jsonl"
    record_evaluation(ledger_path, _evaluation())
    assert (
        has_been_evaluated(
            ledger_path, strategy_version="a_different_version", instrument="XAUUSD", mode="scalp"
        )
        is False
    )


def test_record_and_has_been_evaluated_round_trip(tmp_path):
    ledger_path = tmp_path / "final_oos.jsonl"
    record_evaluation(ledger_path, _evaluation())
    assert (
        has_been_evaluated(
            ledger_path,
            strategy_version="trend_pullback_v1",
            instrument="XAUUSD",
            mode="scalp",
        )
        is True
    )


def test_record_evaluation_is_append_only(tmp_path):
    ledger_path = tmp_path / "final_oos.jsonl"
    record_evaluation(ledger_path, _evaluation(strategy_version="v1"))
    record_evaluation(ledger_path, _evaluation(strategy_version="v2"))
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert has_been_evaluated(ledger_path, strategy_version="v1", instrument="XAUUSD", mode="scalp")
    assert has_been_evaluated(ledger_path, strategy_version="v2", instrument="XAUUSD", mode="scalp")


def test_assert_not_yet_evaluated_raises_on_identical_key(tmp_path):
    ledger_path = tmp_path / "final_oos.jsonl"
    record_evaluation(ledger_path, _evaluation())

    with pytest.raises(FinalOosAlreadyEvaluatedError):
        assert_not_yet_evaluated(
            ledger_path,
            strategy_version="trend_pullback_v1",
            instrument="XAUUSD",
            mode="scalp",
        )


def test_assert_not_yet_evaluated_passes_for_a_new_strategy_version(tmp_path):
    """Directly proves the rule: 'any adjustment creates a new strategy
    version requiring new unseen data' -- a new version is never blocked
    by a prior evaluation of a different version.
    """
    ledger_path = tmp_path / "final_oos.jsonl"
    record_evaluation(ledger_path, _evaluation(strategy_version="trend_pullback_v1"))

    assert_not_yet_evaluated(
        ledger_path,
        strategy_version="trend_pullback_v2",
        instrument="XAUUSD",
        mode="scalp",
    )  # must not raise


def test_assert_not_yet_evaluated_passes_for_a_different_instrument(tmp_path):
    ledger_path = tmp_path / "final_oos.jsonl"
    record_evaluation(ledger_path, _evaluation(instrument="XAUUSD"))

    assert_not_yet_evaluated(
        ledger_path,
        strategy_version="trend_pullback_v1",
        instrument="EURUSD",
        mode="scalp",
    )  # must not raise


def test_dataset_note_is_not_part_of_the_guard_key(tmp_path):
    """A deeper future history pull for the same instrument (a different
    dataset_note) must not bypass the guard for an already-evaluated
    version -- dataset_note is audit context only.
    """
    ledger_path = tmp_path / "final_oos.jsonl"
    record_evaluation(ledger_path, _evaluation(dataset_note="180d, TwelveData"))

    with pytest.raises(FinalOosAlreadyEvaluatedError):
        assert_not_yet_evaluated(
            ledger_path,
            strategy_version="trend_pullback_v1",
            instrument="XAUUSD",
            mode="scalp",
        )
