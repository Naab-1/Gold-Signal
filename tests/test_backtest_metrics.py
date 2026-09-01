from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.backtest.metrics import compute_summary
from goldsignal.backtest.models import BacktestTrade, TargetFill
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.trade_management import TradeManagementPreset

START = datetime(2026, 1, 1, tzinfo=UTC)


def _trade(realized_r, *, target_labels=(), is_full_stop=False, breakeven=False):
    fills = [
        TargetFill(
            label=lbl,
            price=100 + i,
            timestamp=START,
            allocation=0.5,
            r_multiple=1.0,
            r_contribution=0.5,
        )
        for i, lbl in enumerate(target_labels)
    ]
    return BacktestTrade(
        signal_id="s",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="v1",
        trade_management_preset=TradeManagementPreset.BALANCED,
        direction=SignalDirection.BUY,
        signal_timestamp=START,
        fill_timestamp=START,
        fill_price=100.0,
        initial_stop_loss=95.0,
        risk=5.0,
        target_fills=fills,
        exit_timestamp=START + timedelta(hours=1),
        exit_price=100.0,
        exit_reason="stop",
        realized_r=realized_r,
        is_full_stop=is_full_stop,
        breakeven_triggered=breakeven,
    )


def test_empty_trade_list_returns_zeroed_summary():
    s = compute_summary(
        [],
        strategy_mode=StrategyMode.SCALP,
        preset=TradeManagementPreset.BALANCED,
        split_label="development",
    )
    assert s.total_trades == 0
    assert s.win_rate == 0.0
    assert s.profit_factor is None
    assert s.avg_win_r is None


def test_summary_arithmetic():
    trades = [
        _trade(2.0, target_labels=["TP1"]),
        _trade(-1.0, is_full_stop=True),
        _trade(1.5, target_labels=["TP1", "TP2"], breakeven=True),
        _trade(-1.0, is_full_stop=True),
        _trade(-0.5, breakeven=True),
    ]
    s = compute_summary(
        trades,
        strategy_mode=StrategyMode.SCALP,
        preset=TradeManagementPreset.BALANCED,
        split_label="development",
    )

    assert s.total_trades == 5
    assert s.win_rate == pytest.approx(0.4)
    assert s.loss_rate == pytest.approx(0.6)
    assert s.avg_win_r == pytest.approx(1.75)
    assert s.avg_loss_r == pytest.approx(-2.5 / 3)
    assert s.expectancy_r == pytest.approx(0.2)
    assert s.profit_factor == pytest.approx(3.5 / 2.5)
    assert s.max_drawdown_r == pytest.approx(1.5)
    assert s.max_consecutive_losses == 2
    assert s.total_return_r == pytest.approx(1.0)
    assert s.tp1_hit_rate == pytest.approx(2 / 5)
    assert s.tp2_hit_rate == pytest.approx(1 / 5)
    assert s.tp3_hit_rate == 0.0
    assert s.full_stop_rate == pytest.approx(2 / 5)
    assert s.breakeven_rate == pytest.approx(2 / 5)


def test_profit_factor_none_when_no_losses():
    trades = [_trade(1.0), _trade(2.0)]
    s = compute_summary(
        trades,
        strategy_mode=StrategyMode.SCALP,
        preset=TradeManagementPreset.BALANCED,
        split_label="development",
    )
    assert s.profit_factor is None
    assert s.avg_loss_r is None
