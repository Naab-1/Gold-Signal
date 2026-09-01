"""Trading-cost estimation shared by live signal generation and backtesting,
so the two can never silently drift apart.

Phase 1 uses each mode's conservative *configured* spread/slippage
estimate (there is no historical bid/ask data yet — that arrives with a
real data provider in Phase 3). Costs are expressed in price units (USD)
and applied once as a round-trip estimate, which is a deliberate
simplification worth revisiting once real spread data is available.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostEstimate:
    spread: float
    slippage: float
    transaction_cost: float = 0.0

    def __post_init__(self) -> None:
        if self.spread < 0 or self.slippage < 0 or self.transaction_cost < 0:
            raise ValueError("spread, slippage, and transaction_cost must not be negative")

    @property
    def total(self) -> float:
        return self.spread + self.slippage + self.transaction_cost


def estimate_costs(spread: float, slippage: float, transaction_cost: float = 0.0) -> CostEstimate:
    return CostEstimate(spread=spread, slippage=slippage, transaction_cost=transaction_cost)


def net_reward_r(
    *, entry: float, stop_loss: float, target_price: float, costs: CostEstimate
) -> float:
    """Reward-to-risk of `target_price`, net of estimated trading costs.

    risk = |entry - stop_loss| (i.e. "1R"). Costs are subtracted from the
    gross price move before dividing by risk.
    """
    risk = abs(entry - stop_loss)
    if risk <= 0:
        raise ValueError("risk (|entry - stop_loss|) must be positive")
    gross_reward = abs(target_price - entry)
    net_reward = gross_reward - costs.total
    return net_reward / risk


def gross_reward_r(*, entry: float, stop_loss: float, target_price: float) -> float:
    """Reward-to-risk of `target_price` before costs — the value stored on
    a ProfitTarget as its r_multiple.
    """
    risk = abs(entry - stop_loss)
    if risk <= 0:
        raise ValueError("risk (|entry - stop_loss|) must be positive")
    return abs(target_price - entry) / risk
