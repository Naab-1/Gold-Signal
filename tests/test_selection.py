"""Tests for the Phase 8 selection-requirements gate. Each criterion is
exercised independently with a constructed `CandidateEvaluation` so a
failure's specific reason can be checked, not just the pass/fail
verdict.
"""

from __future__ import annotations

from goldsignal.analysis.performance_evaluation import CandidateEvaluation
from goldsignal.analysis.selection import (
    SelectionCriteria,
    evaluate_selection,
    evaluate_selection_batch,
)
from goldsignal.backtest.models import BacktestSummary
from goldsignal.models.signal import StrategyMode
from goldsignal.strategy.trade_management import TradeManagementPreset


def _summary(expectancy_r: float, total_trades: int, split_label: str) -> BacktestSummary:
    return BacktestSummary(
        strategy_mode=StrategyMode.TREND_PULLBACK,
        trade_management_preset=TradeManagementPreset.BALANCED,
        split_label=split_label,
        total_trades=total_trades,
        win_rate=0.5,
        loss_rate=0.5,
        avg_win_r=1.5,
        avg_loss_r=-1.0,
        expectancy_r=expectancy_r,
        profit_factor=1.5,
        max_drawdown_r=-3.0,
        max_consecutive_losses=3,
        total_return_r=expectancy_r * total_trades,
        tp1_hit_rate=0.5,
        tp2_hit_rate=0.2,
        tp3_hit_rate=0.1,
        full_stop_rate=0.4,
        breakeven_rate=0.0,
    )


def _evaluation(
    *, family="test_family", dev_trades, dev_expectancy, val_trades, val_expectancy
) -> CandidateEvaluation:
    return CandidateEvaluation(
        family=family,
        instrument="XAUUSD",
        mode=StrategyMode.TREND_PULLBACK,
        development=_summary(dev_expectancy, dev_trades, "development"),
        validation=_summary(val_expectancy, val_trades, "validation"),
        development_by_regime={},
        validation_by_regime={},
        development_by_session={},
        validation_by_session={},
    )


DEFAULT_CRITERIA = SelectionCriteria()


def test_passes_when_every_criterion_is_cleared():
    evaluation = _evaluation(dev_trades=50, dev_expectancy=0.3, val_trades=20, val_expectancy=0.2)
    result = evaluate_selection(evaluation, DEFAULT_CRITERIA)
    assert result.passed
    assert result.failures == []


def test_fails_on_insufficient_development_trades():
    evaluation = _evaluation(dev_trades=10, dev_expectancy=0.3, val_trades=20, val_expectancy=0.2)
    result = evaluate_selection(evaluation, DEFAULT_CRITERIA)
    assert not result.passed
    assert any("development trades" in f for f in result.failures)
    assert not any("validation trades" in f for f in result.failures)


def test_fails_on_insufficient_validation_trades():
    evaluation = _evaluation(dev_trades=50, dev_expectancy=0.3, val_trades=5, val_expectancy=0.2)
    result = evaluate_selection(evaluation, DEFAULT_CRITERIA)
    assert not result.passed
    assert any("validation trades" in f for f in result.failures)


def test_fails_on_non_positive_development_expectancy():
    evaluation = _evaluation(dev_trades=50, dev_expectancy=-0.05, val_trades=20, val_expectancy=0.2)
    result = evaluate_selection(evaluation, DEFAULT_CRITERIA)
    assert not result.passed
    assert any("development expectancy" in f for f in result.failures)


def test_fails_on_non_positive_validation_expectancy_even_with_strong_development():
    # Mirrors Phase 7's real Trend Pullback finding: strong development,
    # negative validation -- must fail, not pass on development alone.
    evaluation = _evaluation(dev_trades=50, dev_expectancy=0.5, val_trades=20, val_expectancy=-0.1)
    result = evaluate_selection(evaluation, DEFAULT_CRITERIA)
    assert not result.passed
    assert any("validation expectancy" in f for f in result.failures)


def test_reports_every_failed_criterion_not_just_the_first():
    # Mirrors Phase 7's real Breakout and Retest finding: looks great on
    # a tiny sample, zero validation trades.
    evaluation = _evaluation(dev_trades=5, dev_expectancy=1.18, val_trades=0, val_expectancy=0.0)
    result = evaluate_selection(evaluation, DEFAULT_CRITERIA)
    assert not result.passed
    assert any("development trades" in f for f in result.failures)
    assert any("validation trades" in f for f in result.failures)
    assert any("validation expectancy" in f for f in result.failures)


def test_evaluate_selection_batch_preserves_order_and_family_names():
    evaluations = [
        _evaluation(
            family="a", dev_trades=50, dev_expectancy=0.3, val_trades=20, val_expectancy=0.2
        ),
        _evaluation(family="b", dev_trades=5, dev_expectancy=1.0, val_trades=0, val_expectancy=0.0),
    ]
    results = evaluate_selection_batch(evaluations, DEFAULT_CRITERIA)
    assert [r.family for r in results] == ["a", "b"]
    assert results[0].passed
    assert not results[1].passed
