"""Turn a list of BacktestTrade into a BacktestSummary. All figures are in
R (risk multiples), post-cost, since no account balance/currency exists
yet (that's Phase 4) — never presented as a probability or guarantee.
"""

from __future__ import annotations

from goldsignal.backtest.models import BacktestSummary, BacktestTrade
from goldsignal.models.signal import StrategyMode
from goldsignal.strategy.trade_management import TradeManagementPreset


def _hit_rate(trades: list[BacktestTrade], label: str) -> float:
    if not trades:
        return 0.0
    count = sum(1 for t in trades if any(tf.label == label for tf in t.target_fills))
    return count / len(trades)


def _max_drawdown_r(trades: list[BacktestTrade]) -> float:
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t.realized_r
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)
    return max_dd


def _max_consecutive_losses(trades: list[BacktestTrade]) -> int:
    max_streak = 0
    streak = 0
    for t in trades:
        if t.realized_r <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return max_streak


def compute_summary(
    trades: list[BacktestTrade],
    *,
    strategy_mode: StrategyMode,
    preset: TradeManagementPreset,
    split_label: str,
) -> BacktestSummary:
    n = len(trades)
    if n == 0:
        return BacktestSummary(
            strategy_mode=strategy_mode,
            trade_management_preset=preset,
            split_label=split_label,
            total_trades=0,
            win_rate=0.0,
            loss_rate=0.0,
            avg_win_r=None,
            avg_loss_r=None,
            expectancy_r=0.0,
            profit_factor=None,
            max_drawdown_r=0.0,
            max_consecutive_losses=0,
            total_return_r=0.0,
            tp1_hit_rate=0.0,
            tp2_hit_rate=0.0,
            tp3_hit_rate=0.0,
            full_stop_rate=0.0,
            breakeven_rate=0.0,
        )

    r_values = [t.realized_r for t in trades]
    wins = [r for r in r_values if r > 0]
    losses = [r for r in r_values if r <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    return BacktestSummary(
        strategy_mode=strategy_mode,
        trade_management_preset=preset,
        split_label=split_label,
        total_trades=n,
        win_rate=len(wins) / n,
        loss_rate=len(losses) / n,
        avg_win_r=(gross_win / len(wins)) if wins else None,
        avg_loss_r=(sum(losses) / len(losses)) if losses else None,
        expectancy_r=sum(r_values) / n,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else None,
        max_drawdown_r=_max_drawdown_r(trades),
        max_consecutive_losses=_max_consecutive_losses(trades),
        total_return_r=sum(r_values),
        tp1_hit_rate=_hit_rate(trades, "TP1"),
        tp2_hit_rate=_hit_rate(trades, "TP2"),
        tp3_hit_rate=_hit_rate(trades, "TP3"),
        full_stop_rate=sum(1 for t in trades if t.is_full_stop) / n,
        breakeven_rate=sum(1 for t in trades if t.breakeven_triggered) / n,
    )
