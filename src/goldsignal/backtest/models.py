"""Backtest trade/result models.

`realized_r` on a BacktestTrade is always net of the trade's estimated
costs and always measured against the *actual* fill price (which may
differ slightly from the signal's nominal entry_price due to spread,
slippage, and next-candle-open execution) — not the signal's nominal risk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from goldsignal.models.signal import SignalDirection, StrategyMode, StrategySignal
from goldsignal.strategy.trade_management import TradeManagementPreset


@dataclass(frozen=True)
class OpenedTrade:
    """A BUY/SELL signal that was actually filled during walk-forward
    simulation. Preset-independent — trade *management* (targets/breakeven)
    is simulated separately per preset from this.
    """

    signal: StrategySignal
    fill_timestamp: datetime
    fill_price: float
    fill_candle_index: int  # index into the entry candle series
    gapped_through_stop: bool  # True if the fill itself already crossed the stop


@dataclass(frozen=True)
class TargetFill:
    label: str
    price: float
    timestamp: datetime
    allocation: float  # fraction of the original position closed here
    r_multiple: float  # unweighted R achieved at this price
    r_contribution: float  # allocation * r_multiple


@dataclass(frozen=True)
class StopAdjustment:
    timestamp: datetime
    new_stop: float
    reason: str


@dataclass(frozen=True)
class BacktestTrade:
    signal_id: str
    strategy_mode: StrategyMode
    strategy_version: str
    trade_management_preset: TradeManagementPreset
    direction: SignalDirection
    signal_timestamp: datetime
    fill_timestamp: datetime
    fill_price: float
    initial_stop_loss: float
    risk: float  # |fill_price - initial_stop_loss|, actual realized "1R" in price units
    target_fills: list[TargetFill] = field(default_factory=list)
    stop_adjustments: list[StopAdjustment] = field(default_factory=list)
    exit_timestamp: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = (
        ""  # "stop" | "breakeven_stop" | "all_targets_hit" | "data_end_mark_to_market"
    )
    realized_r: float = 0.0
    is_full_stop: bool = False
    breakeven_triggered: bool = False


@dataclass(frozen=True)
class BacktestSummary:
    strategy_mode: StrategyMode
    trade_management_preset: TradeManagementPreset
    split_label: str  # "development" | "out_of_sample"
    total_trades: int
    win_rate: float
    loss_rate: float
    avg_win_r: float | None
    avg_loss_r: float | None
    expectancy_r: float
    profit_factor: float | None  # None when there are no losses (undefined)
    max_drawdown_r: float
    max_consecutive_losses: int
    total_return_r: float
    tp1_hit_rate: float
    tp2_hit_rate: float
    tp3_hit_rate: float
    full_stop_rate: float
    breakeven_rate: float
