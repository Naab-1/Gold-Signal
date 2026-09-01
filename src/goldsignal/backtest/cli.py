"""Run a mode x preset backtest grid against the configured data provider.

Uses whatever GOLDSIGNAL_DATA_PROVIDER is set to (mock or twelvedata) —
same provider selection as live/run_once.py, loaded from .env.

Usage:
    python -m goldsignal.backtest.cli --mode both --preset all
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from dotenv import load_dotenv

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
from goldsignal.config import (
    GlobalSettings,
    ModeConfig,
    load_daytrade_config,
    load_global_settings,
    load_scalp_config,
)
from goldsignal.data.provider import get_data_provider
from goldsignal.data.validation import validate_candles
from goldsignal.logging_config import configure_logging
from goldsignal.strategy.day_trade import DayTradeStrategy
from goldsignal.strategy.scalp import ScalpStrategy
from goldsignal.strategy.trade_management import BreakevenRule, TradeManagementPreset
from goldsignal.utils.time import utc_now

logger = logging.getLogger(__name__)

_MODE_BUILDERS = {
    "scalp": (load_scalp_config, ScalpStrategy),
    "daytrade": (load_daytrade_config, DayTradeStrategy),
}

_ALL_PRESETS = list(TradeManagementPreset)


def _run_mode(
    mode_key: str,
    *,
    settings: GlobalSettings,
    candle_count: int,
    presets: list[TradeManagementPreset],
    split_ratio: float,
) -> tuple[list[BacktestTrade], list[BacktestSummary]]:
    instrument = settings.instrument
    config_loader, strategy_cls = _MODE_BUILDERS[mode_key]
    config: ModeConfig = config_loader()
    strategy = strategy_cls(config, instrument)

    provider = get_data_provider(settings)
    end = utc_now()
    start = end - config.entry_timeframe.duration * candle_count
    entry_raw = provider.get_candles(instrument, config.entry_timeframe, start, end)
    confirm_raw = provider.get_candles(instrument, config.confirmation_timeframe, start, end)

    entry_result = validate_candles(entry_raw, config.entry_timeframe, end)
    confirm_result = validate_candles(confirm_raw, config.confirmation_timeframe, end)
    for issue in entry_result.issues + confirm_result.issues:
        logger.info("mode=%s data validation: %s", mode_key, issue)
    entry_candles = entry_result.clean_candles
    confirmation_candles = confirm_result.clean_candles

    logger.info(
        "mode=%s provider=%s generating signals over %d entry candles (%s .. %s)",
        mode_key,
        settings.data_provider,
        len(entry_candles),
        entry_candles[0].timestamp if entry_candles else "n/a",
        entry_candles[-1].timestamp if entry_candles else "n/a",
    )
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
    parser.add_argument("--candles", type=int, default=3000)
    parser.add_argument("--split-ratio", type=float, default=DEFAULT_SPLIT_RATIO)
    parser.add_argument("--output-dir", default="backtest_output")
    args = parser.parse_args()

    load_dotenv()
    configure_logging("INFO")
    settings = load_global_settings()
    print(f"Data provider: {settings.data_provider}")

    modes = ["scalp", "daytrade"] if args.mode == "both" else [args.mode]
    presets = _ALL_PRESETS if args.preset == "all" else [TradeManagementPreset(args.preset)]

    all_trades: list[BacktestTrade] = []
    all_summaries: list[BacktestSummary] = []
    for mode_key in modes:
        trades, summaries = _run_mode(
            mode_key,
            settings=settings,
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
