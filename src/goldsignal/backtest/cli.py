"""Run a mode x preset backtest grid against the mock data provider.

Usage:
    python -m goldsignal.backtest.cli --mode both --preset all
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from pathlib import Path

from goldsignal.backtest.engine import generate_signals_walk_forward, simulate_trade_management
from goldsignal.backtest.export import (
    export_summaries_csv,
    export_summaries_json,
    export_trades_csv,
    export_trades_json,
)
from goldsignal.backtest.metrics import compute_summary
from goldsignal.backtest.models import BacktestSummary, BacktestTrade
from goldsignal.backtest.split import DEFAULT_SPLIT_RATIO, split_cutoff_timestamp, split_trades
from goldsignal.config import ModeConfig, load_daytrade_config, load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.logging_config import configure_logging
from goldsignal.strategy.day_trade import DayTradeStrategy
from goldsignal.strategy.scalp import ScalpStrategy
from goldsignal.strategy.trade_management import BreakevenRule, TradeManagementPreset

logger = logging.getLogger(__name__)

_START = datetime(2020, 1, 1, tzinfo=UTC)

_MODE_BUILDERS = {
    "scalp": (load_scalp_config, ScalpStrategy),
    "daytrade": (load_daytrade_config, DayTradeStrategy),
}

_ALL_PRESETS = list(TradeManagementPreset)


def _run_mode(
    mode_key: str,
    *,
    instrument: str,
    seed: int,
    candle_count: int,
    presets: list[TradeManagementPreset],
    split_ratio: float,
) -> tuple[list[BacktestTrade], list[BacktestSummary]]:
    config_loader, strategy_cls = _MODE_BUILDERS[mode_key]
    config: ModeConfig = config_loader()
    strategy = strategy_cls(config, instrument)

    end = _START + config.entry_timeframe.duration * candle_count
    provider = MockDataProvider(seed=seed, base_price=2400.0, volatility=6.0)
    entry_candles = provider.get_candles(instrument, config.entry_timeframe, _START, end)
    confirmation_candles = provider.get_candles(
        instrument, config.confirmation_timeframe, _START, end
    )

    logger.info("mode=%s generating signals over %d entry candles", mode_key, len(entry_candles))
    opened = generate_signals_walk_forward(strategy, entry_candles, confirmation_candles)
    logger.info("mode=%s opened %d trades", mode_key, len(opened))

    cutoff = split_cutoff_timestamp(entry_candles, split_ratio)
    breakeven_rule = BreakevenRule(
        trigger=config.breakeven_trigger, after_r_multiple=config.breakeven_after_r_multiple
    )

    all_trades: list[BacktestTrade] = []
    all_summaries: list[BacktestSummary] = []
    for preset in presets:
        trades = [
            simulate_trade_management(
                o,
                entry_candles,
                preset=preset,
                shortfall_mode=config.tp_shortfall_handling,
                breakeven_rule=breakeven_rule,
                transaction_cost=config.estimated_transaction_cost,
            )
            for o in opened
        ]
        all_trades.extend(trades)

        development, out_of_sample = split_trades(trades, cutoff)
        all_summaries.append(
            compute_summary(
                development, strategy_mode=strategy.mode, preset=preset, split_label="development"
            )
        )
        all_summaries.append(
            compute_summary(
                out_of_sample,
                strategy_mode=strategy.mode,
                preset=preset,
                split_label="out_of_sample",
            )
        )

    return all_trades, all_summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["scalp", "daytrade", "both"], default="both")
    parser.add_argument(
        "--preset", choices=["conservative", "balanced", "runner", "all"], default="all"
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--candles", type=int, default=3000)
    parser.add_argument("--split-ratio", type=float, default=DEFAULT_SPLIT_RATIO)
    parser.add_argument("--instrument", default="XAUUSD")
    parser.add_argument("--output-dir", default="backtest_output")
    args = parser.parse_args()

    configure_logging("INFO")

    modes = ["scalp", "daytrade"] if args.mode == "both" else [args.mode]
    presets = _ALL_PRESETS if args.preset == "all" else [TradeManagementPreset(args.preset)]

    all_trades: list[BacktestTrade] = []
    all_summaries: list[BacktestSummary] = []
    for mode_key in modes:
        trades, summaries = _run_mode(
            mode_key,
            instrument=args.instrument,
            seed=args.seed,
            candle_count=args.candles,
            presets=presets,
            split_ratio=args.split_ratio,
        )
        all_trades.extend(trades)
        all_summaries.extend(summaries)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    export_trades_csv(all_trades, out_dir / "trades.csv")
    export_trades_json(all_trades, out_dir / "trades.json")
    export_summaries_csv(all_summaries, out_dir / "summary.csv")
    export_summaries_json(all_summaries, out_dir / "summary.json")

    for s in all_summaries:
        print(
            f"{s.strategy_mode.value:10s} {s.trade_management_preset.value:12s} "
            f"{s.split_label:14s} trades={s.total_trades:4d} expectancy_r={s.expectancy_r:+.3f} "
            f"win_rate={s.win_rate:.2%} max_dd_r={s.max_drawdown_r:.2f}"
        )
    print(f"\nWrote results to {out_dir.resolve()}")


if __name__ == "__main__":
    main()
