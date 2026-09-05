"""Tests for the controlled-optimization framework (STRATEGY RESEARCH
AND REPLACEMENT program, Phase 6). Most of these isolate the selection
arithmetic itself (complexity penalty, minimum-improvement gating,
trade-count disqualification) by monkeypatching
`run_candidate_dev_validation` with a fully controlled fake -- the real
walk/backtest machinery is already covered by
`tests/test_candidate_walk.py` and each family's own test suite, so
these tests focus on what's genuinely new: the optimization/selection
logic. One end-to-end test at the bottom wires a real Phase 4 candidate
(Trend Pullback) through the framework against synthetic data, proving
the generic factory-based interface actually works with a real
`Strategy`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from goldsignal.analysis.candidate_walk import CandidateDevValidationSummary
from goldsignal.analysis.optimization import (
    _count_changed_params,
    run_controlled_optimization,
    write_trials_log,
)
from goldsignal.backtest.models import BacktestSummary
from goldsignal.config import load_trend_pullback_mode_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.signal import StrategyMode
from goldsignal.strategy.candidates.trend_pullback import (
    TrendPullbackConfig,
    TrendPullbackStrategy,
    load_trend_pullback_config,
)
from goldsignal.strategy.trade_management import TradeManagementPreset

START = datetime(2026, 1, 1, tzinfo=UTC)


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


class _StubStrategy:
    """A minimal stand-in for a `Strategy` -- carries only the resolved
    params dict, since the fake `run_candidate_dev_validation` below
    reads it directly instead of actually walking any candles.
    """

    def __init__(self, params: dict) -> None:
        self.params = params


def _identity_build_family_config(params: dict) -> dict:
    return dict(params)


def _stub_build_strategy(params: dict) -> _StubStrategy:
    return _StubStrategy(params)


def _patch_dev_validation(monkeypatch, expectancy_by_key: dict, *, key_field: str, total_trades=50):
    """Replaces `run_candidate_dev_validation` with a fake that returns a
    controlled development expectancy based on `strategy.params[key_field]`
    -- isolates the optimization/selection arithmetic from any real
    strategy or candle data.
    """

    def fake_run_candidate_dev_validation(
        strategy, mode, entry_candles, confirmation_candles, **kwargs
    ):
        expectancy = expectancy_by_key[strategy.params[key_field]]
        return CandidateDevValidationSummary(
            development=_summary(expectancy, total_trades, "development"),
            validation=_summary(expectancy * 0.8, total_trades, "validation"),
            grade_counts={},
            total_days=30,
            zero_signal_days=5,
        )

    monkeypatch.setattr(
        "goldsignal.analysis.optimization.run_candidate_dev_validation",
        fake_run_candidate_dev_validation,
    )


def _run(monkeypatch, expectancy_by_key, *, param_grid, baseline_value=1, **kwargs):
    _patch_dev_validation(monkeypatch, expectancy_by_key, key_field="x")
    return run_controlled_optimization(
        build_family_config=_identity_build_family_config,
        build_strategy=_stub_build_strategy,
        baseline_params={"x": baseline_value},
        param_grid=param_grid,
        mode=StrategyMode.TREND_PULLBACK,
        entry_candles=[],
        confirmation_candles=[],
        **kwargs,
    )


# --- _count_changed_params ----------------------------------------------------


def test_count_changed_params_counts_only_differing_fields():
    baseline = {"a": 1, "b": 2, "c": 3}
    assert _count_changed_params({"a": 1, "b": 2, "c": 3}, baseline) == 0
    assert _count_changed_params({"a": 1, "b": 99, "c": 3}, baseline) == 1
    assert _count_changed_params({"a": 9, "b": 99, "c": 3}, baseline) == 2


# --- Selection arithmetic (monkeypatched dev-validation) ---------------------


def test_selects_baseline_when_no_candidate_improves(monkeypatch):
    # Every grid value performs worse than or equal to baseline.
    result = _run(
        monkeypatch,
        {1: 0.10, 2: 0.05, 3: 0.02},
        param_grid={"x": [2, 3]},
        baseline_value=1,
    )
    assert result.selected_is_baseline
    assert result.selected_trial.params == {"x": 1}
    assert len(result.trials) == 3  # baseline + 2 grid combos


def test_selects_better_configuration_when_improvement_exceeds_penalty_and_margin(monkeypatch):
    # x=2 improves dev expectancy by 0.20R for one changed parameter --
    # comfortably clears the default penalty (0.02) and min_improvement (0.02).
    result = _run(
        monkeypatch,
        {1: 0.10, 2: 0.30},
        param_grid={"x": [2]},
    )
    assert not result.selected_is_baseline
    assert result.selected_trial.params == {"x": 2}
    assert result.selected_trial.penalized_score == pytest.approx(0.30 - 0.02)


def test_does_not_select_improvement_too_small_to_clear_penalty_and_margin(monkeypatch):
    # x=2 improves raw dev expectancy by only 0.01R -- smaller than the
    # complexity penalty for one changed parameter (0.02), so it should
    # lose to the baseline once penalized.
    result = _run(
        monkeypatch,
        {1: 0.10, 2: 0.11},
        param_grid={"x": [2]},
    )
    assert result.selected_is_baseline


def test_min_improvement_r_gates_marginal_wins_even_after_penalty(monkeypatch):
    # x=2 clears the complexity penalty but not by enough to beat a
    # stricter min_improvement_r requirement.
    result = _run(
        monkeypatch,
        {1: 0.10, 2: 0.20},
        param_grid={"x": [2]},
        complexity_penalty_per_param=0.02,
        min_improvement_r=0.5,
    )
    assert result.selected_is_baseline


def test_disqualifies_trials_below_min_dev_trades(monkeypatch):
    _patch_dev_validation(monkeypatch, {1: 0.10, 2: 0.90}, key_field="x", total_trades=3)
    result = run_controlled_optimization(
        build_family_config=_identity_build_family_config,
        build_strategy=_stub_build_strategy,
        baseline_params={"x": 1},
        param_grid={"x": [2]},
        mode=StrategyMode.TREND_PULLBACK,
        entry_candles=[],
        confirmation_candles=[],
        min_dev_trades=20,
    )
    # x=2 would look far better on raw expectancy, but with only 3 dev
    # trades it must be disqualified rather than selected.
    disqualified = [t for t in result.trials if t.params == {"x": 2}][0]
    assert disqualified.penalized_score is None
    assert disqualified.disqualified_reason is not None
    assert result.selected_is_baseline


def test_baseline_disqualified_selects_baseline_with_explanatory_reason(monkeypatch):
    _patch_dev_validation(monkeypatch, {1: 0.10, 2: 0.90}, key_field="x", total_trades=1)
    result = run_controlled_optimization(
        build_family_config=_identity_build_family_config,
        build_strategy=_stub_build_strategy,
        baseline_params={"x": 1},
        param_grid={"x": [2]},
        mode=StrategyMode.TREND_PULLBACK,
        entry_candles=[],
        confirmation_candles=[],
        min_dev_trades=20,
    )
    assert result.selected_is_baseline
    assert result.selected_trial is result.baseline_trial
    assert "too low" in result.selection_reason


def test_baseline_never_double_counted_when_present_in_grid(monkeypatch):
    _patch_dev_validation(monkeypatch, {1: 0.10, 2: 0.05}, key_field="x")
    result = run_controlled_optimization(
        build_family_config=_identity_build_family_config,
        build_strategy=_stub_build_strategy,
        baseline_params={"x": 1},
        param_grid={"x": [1, 2]},  # grid includes the baseline's own value
        mode=StrategyMode.TREND_PULLBACK,
        entry_candles=[],
        confirmation_candles=[],
    )
    assert len(result.trials) == 2  # not 3 -- x=1 isn't evaluated twice


# --- write_trials_log ---------------------------------------------------------


def test_write_trials_log_produces_valid_json_with_expected_keys(monkeypatch, tmp_path):
    result = _run(monkeypatch, {1: 0.10, 2: 0.05}, param_grid={"x": [2]})
    out = tmp_path / "trials.json"
    write_trials_log(result, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "baseline_trial" in payload
    assert "selected_trial" in payload
    assert "trials" in payload
    assert len(payload["trials"]) == len(result.trials)
    assert payload["selected_is_baseline"] is True


# --- End-to-end: a real Phase 4 candidate wired through the framework -------


def test_end_to_end_with_real_trend_pullback_strategy_and_synthetic_data():
    mode_config = load_trend_pullback_mode_config(
        {
            "GOLDSIGNAL_TRENDPULLBACK_COOLDOWN_MINUTES": "0",
            "GOLDSIGNAL_TRENDPULLBACK_MAX_SIGNALS_PER_SESSION": "10000",
        }
    )
    baseline_config = load_trend_pullback_config(
        {
            "GOLDSIGNAL_TRENDPULLBACK_COOLDOWN_MINUTES": "0",
            "GOLDSIGNAL_TRENDPULLBACK_MAX_SIGNALS_PER_SESSION": "10000",
            "GOLDSIGNAL_TRENDPULLBACK_MIN_NET_REWARD_R": "0.1",
        }
    )
    baseline_params = {
        "trend_strength_atr_multiple": baseline_config.trend_strength_atr_multiple,
        "pullback_rsi_trigger": baseline_config.pullback_rsi_trigger,
        "pullback_rsi_confirm": baseline_config.pullback_rsi_confirm,
        "pullback_lookback_candles": baseline_config.pullback_lookback_candles,
        "max_extension_atr_multiple": baseline_config.max_extension_atr_multiple,
        "structure_lookbacks": baseline_config.structure_lookbacks,
        "min_net_reward_r": baseline_config.min_net_reward_r,
        "cooldown_minutes": baseline_config.cooldown_minutes,
        "max_signals_per_session": baseline_config.max_signals_per_session,
        "setup_expiration_candles": baseline_config.setup_expiration_candles,
    }

    provider = MockDataProvider(seed=7, base_price=2400.0, volatility=6.0)
    end = START + mode_config.entry_timeframe.duration * 4000
    entry = provider.get_candles("XAUUSD", mode_config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", mode_config.confirmation_timeframe, START, end)

    result = run_controlled_optimization(
        build_family_config=lambda params: TrendPullbackConfig(**params),
        build_strategy=lambda fc: TrendPullbackStrategy(mode_config, fc, "XAUUSD"),
        baseline_params=baseline_params,
        param_grid={"max_extension_atr_multiple": [1.0, 2.0]},
        mode=StrategyMode.TREND_PULLBACK,
        entry_candles=entry,
        confirmation_candles=confirm,
        min_dev_trades=1,  # synthetic data has no real edge; just proving the wiring works
    )

    assert len(result.trials) == 3  # baseline + 2 grid values
    assert result.selected_trial in result.trials
    assert result.baseline_trial.params == baseline_params
    for trial in result.trials:
        assert trial.development.split_label == "development"
        assert trial.validation.split_label == "validation"
