import pytest

from goldsignal.models.signal import SignalDirection
from goldsignal.strategy.cost_model import estimate_costs
from goldsignal.strategy.targets import build_targets

COSTS = estimate_costs(spread=0.5, slippage=0.5)  # total = 1.0


def test_build_targets_buy_selects_up_to_three_when_allowed():
    targets = build_targets(
        direction=SignalDirection.BUY,
        entry=100,
        stop_loss=95,  # risk = 5
        candidate_levels=[102, 106, 111, 120],
        costs=COSTS,
        min_net_reward_r=1.0,
        allow_tp3=True,
    )
    labels = [t.label for t in targets]
    prices = [t.price for t in targets]
    assert labels == ["TP1", "TP2", "TP3"]
    assert prices == [106, 111, 120]
    assert targets[0].r_multiple == pytest.approx(1.2)
    assert targets[1].r_multiple == pytest.approx(2.2)
    assert targets[2].r_multiple == pytest.approx(4.0)


def test_build_targets_caps_at_two_when_tp3_not_allowed():
    targets = build_targets(
        direction=SignalDirection.BUY,
        entry=100,
        stop_loss=95,
        candidate_levels=[102, 106, 111, 120],
        costs=COSTS,
        min_net_reward_r=1.0,
        allow_tp3=False,
    )
    assert [t.label for t in targets] == ["TP1", "TP2"]


def test_build_targets_sell_mirrors_buy():
    targets = build_targets(
        direction=SignalDirection.SELL,
        entry=100,
        stop_loss=105,  # risk = 5
        candidate_levels=[98, 94, 89, 80],
        costs=COSTS,
        min_net_reward_r=1.0,
        allow_tp3=True,
    )
    prices = [t.price for t in targets]
    assert prices == [94, 89, 80]


def test_build_targets_returns_empty_when_nothing_clears_threshold():
    targets = build_targets(
        direction=SignalDirection.BUY,
        entry=100,
        stop_loss=95,
        candidate_levels=[100.5, 101],  # tiny moves, can't clear costs
        costs=COSTS,
        min_net_reward_r=1.0,
        allow_tp3=True,
    )
    assert targets == []


def test_build_targets_ignores_levels_on_wrong_side_of_entry():
    targets = build_targets(
        direction=SignalDirection.BUY,
        entry=100,
        stop_loss=95,
        candidate_levels=[90, 80],  # below entry, invalid for a BUY
        costs=COSTS,
        min_net_reward_r=1.0,
        allow_tp3=True,
    )
    assert targets == []
