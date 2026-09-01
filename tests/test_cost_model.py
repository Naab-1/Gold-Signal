import pytest

from goldsignal.strategy.cost_model import (
    CostEstimate,
    estimate_costs,
    gross_reward_r,
    net_reward_r,
)


def test_cost_estimate_total():
    c = estimate_costs(spread=0.3, slippage=0.2)
    assert c.total == pytest.approx(0.5)


def test_cost_estimate_rejects_negative():
    with pytest.raises(ValueError):
        CostEstimate(spread=-1, slippage=0)


def test_net_reward_r_subtracts_costs():
    costs = estimate_costs(spread=0.5, slippage=0.5)  # total 1.0
    # entry=100, stop=95 -> risk=5; target=110 -> gross reward=10, net=9 -> 9/5=1.8
    r = net_reward_r(entry=100, stop_loss=95, target_price=110, costs=costs)
    assert r == pytest.approx(1.8)


def test_gross_reward_r_ignores_costs():
    r = gross_reward_r(entry=100, stop_loss=95, target_price=110)
    assert r == pytest.approx(2.0)


def test_net_reward_r_requires_positive_risk():
    costs = estimate_costs(0, 0)
    with pytest.raises(ValueError):
        net_reward_r(entry=100, stop_loss=100, target_price=110, costs=costs)
