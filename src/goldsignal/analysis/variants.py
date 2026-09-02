"""Named, deliberately-relaxed ModeConfig variants for side-by-side
comparison against the current production settings.

Comparison only — nothing here writes to config.py or changes any
default. Reuses the existing backtest engine/metrics unchanged; only the
ModeConfig fed into it differs per variant.
"""

from __future__ import annotations

import dataclasses

from goldsignal.backtest.engine import generate_signals_walk_forward, simulate_trade_management
from goldsignal.backtest.metrics import compute_summary
from goldsignal.backtest.models import BacktestSummary
from goldsignal.config import ModeConfig
from goldsignal.models.candle import Candle
from goldsignal.models.signal import StrategyMode
from goldsignal.strategy.trade_management import BreakevenRule, TradeManagementPreset


def build_variants(base: ModeConfig) -> dict[str, ModeConfig]:
    relaxed_chop = dataclasses.replace(
        base, chop_filter_atr_multiple=base.chop_filter_atr_multiple / 2
    )
    relaxed_rsi = dataclasses.replace(
        base,
        rsi_buy_threshold=max(base.rsi_buy_threshold - 10, 0),
        rsi_sell_threshold=min(base.rsi_sell_threshold + 10, 100),
        rsi_overbought=min(base.rsi_overbought + 10, 100),
        rsi_oversold=max(base.rsi_oversold - 10, 0),
    )
    relaxed_retest = dataclasses.replace(
        base,
        retest_confirm_window=base.retest_confirm_window * 2,
        retest_tolerance_atr_fraction=base.retest_tolerance_atr_fraction * 1.5,
    )
    relaxed_reward = dataclasses.replace(base, min_net_reward_r=base.min_net_reward_r * 0.7)
    relaxed_all = dataclasses.replace(
        base,
        chop_filter_atr_multiple=relaxed_chop.chop_filter_atr_multiple,
        rsi_buy_threshold=relaxed_rsi.rsi_buy_threshold,
        rsi_sell_threshold=relaxed_rsi.rsi_sell_threshold,
        rsi_overbought=relaxed_rsi.rsi_overbought,
        rsi_oversold=relaxed_rsi.rsi_oversold,
        retest_confirm_window=relaxed_retest.retest_confirm_window,
        retest_tolerance_atr_fraction=relaxed_retest.retest_tolerance_atr_fraction,
        min_net_reward_r=relaxed_reward.min_net_reward_r,
    )
    return {
        "current": base,
        "relaxed_chop_filter": relaxed_chop,
        "relaxed_rsi_band": relaxed_rsi,
        "relaxed_retest_window": relaxed_retest,
        "relaxed_min_reward": relaxed_reward,
        "relaxed_all_combined": relaxed_all,
    }


@dataclasses.dataclass
class VariantResult:
    variant_name: str
    config: ModeConfig
    total_trades: int
    trades_per_day: float
    summary: BacktestSummary


def run_comparison(
    strategy_cls: type,
    mode: StrategyMode,
    base_config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    *,
    preset: TradeManagementPreset = TradeManagementPreset.BALANCED,
) -> list[VariantResult]:
    if len(entry_candles) > 1:
        span_days = (
            entry_candles[-1].timestamp - entry_candles[0].timestamp
        ).total_seconds() / 86400
        span_days = max(span_days, 1e-9)
    else:
        span_days = 1.0

    results: list[VariantResult] = []
    for name, config in build_variants(base_config).items():
        strategy = strategy_cls(config, instrument)
        opened = generate_signals_walk_forward(strategy, entry_candles, confirmation_candles)
        breakeven_rule = BreakevenRule(
            trigger=config.breakeven_trigger, after_r_multiple=config.breakeven_after_r_multiple
        )
        trades = [
            simulate_trade_management(
                o,
                entry_candles,
                preset=preset,
                shortfall_mode=config.tp_shortfall_handling,
                breakeven_rule=breakeven_rule,
                transaction_cost=config.estimated_transaction_cost,
                estimated_spread=config.estimated_spread,
                estimated_slippage=config.estimated_slippage,
            )
            for o in opened
        ]
        summary = compute_summary(
            trades, strategy_mode=mode, preset=preset, split_label="full_range"
        )
        results.append(
            VariantResult(
                variant_name=name,
                config=config,
                total_trades=len(trades),
                trades_per_day=len(trades) / span_days,
                summary=summary,
            )
        )
    return results
