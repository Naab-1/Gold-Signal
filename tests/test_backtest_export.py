import csv
import json
from datetime import UTC, datetime

from goldsignal.backtest.export import (
    export_summaries_csv,
    export_summaries_json,
    export_trades_csv,
    export_trades_json,
    to_jsonable,
)
from goldsignal.backtest.metrics import compute_summary
from goldsignal.backtest.models import BacktestTrade, TargetFill
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.trade_management import TradeManagementPreset

START = datetime(2026, 1, 1, tzinfo=UTC)


def _trade():
    return BacktestTrade(
        signal_id="sig1",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="v1",
        trade_management_preset=TradeManagementPreset.BALANCED,
        direction=SignalDirection.BUY,
        signal_timestamp=START,
        fill_timestamp=START,
        fill_price=100.0,
        initial_stop_loss=95.0,
        risk=5.0,
        target_fills=[
            TargetFill(
                label="TP1",
                price=103.0,
                timestamp=START,
                allocation=0.5,
                r_multiple=0.6,
                r_contribution=0.3,
            )
        ],
        exit_reason="all_targets_hit",
        realized_r=0.3,
    )


def test_export_trades_json_round_trips(tmp_path):
    path = tmp_path / "trades.json"
    export_trades_json([_trade()], path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["signal_id"] == "sig1"
    assert data[0]["strategy_mode"] == "SCALP"
    assert data[0]["target_fills"][0]["label"] == "TP1"
    assert data[0]["signal_timestamp"] == START.isoformat()


def test_export_trades_csv_has_header_and_row(tmp_path):
    path = tmp_path / "trades.csv"
    export_trades_csv([_trade(), _trade()], path)
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2
    assert rows[0]["signal_id"] == "sig1"
    assert json.loads(rows[0]["target_fills"])[0]["label"] == "TP1"


def test_export_summaries_json_and_csv(tmp_path):
    summary = compute_summary(
        [_trade()],
        strategy_mode=StrategyMode.SCALP,
        preset=TradeManagementPreset.BALANCED,
        split_label="development",
    )
    json_path = tmp_path / "summary.json"
    csv_path = tmp_path / "summary.csv"
    export_summaries_json([summary], json_path)
    export_summaries_csv([summary], csv_path)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data[0]["strategy_mode"] == "SCALP"
    assert data[0]["total_trades"] == 1

    with csv_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["split_label"] == "development"


def test_to_jsonable_recurses_into_dict_values():
    # A plain dict whose values are dataclasses (e.g. a
    # `dict[str, BacktestSummary]` regime/session breakdown, as used by
    # analysis/performance_evaluation.py::CandidateEvaluation) must have
    # its values converted too, not just be passed through unchanged.
    summary = compute_summary(
        [_trade()],
        strategy_mode=StrategyMode.SCALP,
        preset=TradeManagementPreset.BALANCED,
        split_label="development",
    )
    payload = to_jsonable({"TRENDING": summary, "RANGING": summary})
    assert payload["TRENDING"]["strategy_mode"] == "SCALP"
    assert payload["RANGING"]["total_trades"] == 1
    # Must actually be JSON-serializable now, not just look right in Python.
    json.dumps(payload)


def test_to_jsonable_handles_nested_dict_inside_a_dataclass_field():
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _Wrapper:
        by_regime: dict

    summary = compute_summary(
        [_trade()],
        strategy_mode=StrategyMode.SCALP,
        preset=TradeManagementPreset.BALANCED,
        split_label="development",
    )
    wrapper = _Wrapper(by_regime={"TRENDING": summary})
    payload = to_jsonable(wrapper)
    json.dumps(payload)  # must not raise
    assert payload["by_regime"]["TRENDING"]["total_trades"] == 1
