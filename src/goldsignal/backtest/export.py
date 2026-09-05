"""CSV/JSON export for backtest trades and summaries."""

from __future__ import annotations

import csv
import dataclasses
import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from goldsignal.backtest.models import BacktestSummary, BacktestTrade


def to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/Enums/datetimes/lists/dicts into
    plain JSON-serializable values. Public: also reused by
    `backtest/final_oos_ledger.py`, so this stays the single source of
    truth for "how does this project turn its result objects into JSON"
    rather than a second copy of the same logic drifting out of sync.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {key: to_jsonable(v) for key, v in value.items()}
    return value


def export_trades_json(trades: list[BacktestTrade], path: str | Path) -> None:
    Path(path).write_text(json.dumps([to_jsonable(t) for t in trades], indent=2), encoding="utf-8")


def export_summaries_json(summaries: list[BacktestSummary], path: str | Path) -> None:
    Path(path).write_text(
        json.dumps([to_jsonable(s) for s in summaries], indent=2), encoding="utf-8"
    )


_TRADE_CSV_FIELDS = [
    "signal_id",
    "strategy_mode",
    "strategy_version",
    "trade_management_preset",
    "direction",
    "signal_timestamp",
    "fill_timestamp",
    "fill_price",
    "initial_stop_loss",
    "risk",
    "exit_timestamp",
    "exit_price",
    "exit_reason",
    "realized_r",
    "is_full_stop",
    "breakeven_triggered",
    "target_fills",
    "stop_adjustments",
]


def export_trades_csv(trades: list[BacktestTrade], path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_TRADE_CSV_FIELDS)
        writer.writeheader()
        for t in trades:
            row = to_jsonable(t)
            row["target_fills"] = json.dumps(row["target_fills"])
            row["stop_adjustments"] = json.dumps(row["stop_adjustments"])
            writer.writerow(row)


_SUMMARY_CSV_FIELDS = [
    "strategy_mode",
    "trade_management_preset",
    "split_label",
    "total_trades",
    "win_rate",
    "loss_rate",
    "avg_win_r",
    "avg_loss_r",
    "expectancy_r",
    "profit_factor",
    "max_drawdown_r",
    "max_consecutive_losses",
    "total_return_r",
    "tp1_hit_rate",
    "tp2_hit_rate",
    "tp3_hit_rate",
    "full_stop_rate",
    "breakeven_rate",
]


def export_summaries_csv(summaries: list[BacktestSummary], path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_SUMMARY_CSV_FIELDS)
        writer.writeheader()
        for s in summaries:
            writer.writerow(to_jsonable(s))
