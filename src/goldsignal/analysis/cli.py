"""Signal diagnostics & frequency audit CLI.

Usage:
    python -m goldsignal.analysis.cli frequency --mode scalp --days 180
    python -m goldsignal.analysis.cli compare --mode scalp --days 180
    python -m goldsignal.analysis.cli diagnostics --mode scalp

All three use the real configured data provider (GOLDSIGNAL_DATA_PROVIDER
from .env) — this is a reporting/comparison tool, it never changes
production strategy settings.
"""

from __future__ import annotations

import argparse
import logging
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

from goldsignal.analysis.diagnostics import build_snapshot, fetch_db_stats
from goldsignal.analysis.frequency import analyze_frequency
from goldsignal.analysis.report import (
    format_diagnostics_snapshot,
    format_frequency_report,
    format_variant_comparison,
    write_html_report,
)
from goldsignal.analysis.variants import run_comparison
from goldsignal.config import (
    GlobalSettings,
    load_daytrade_config,
    load_global_settings,
    load_scalp_config,
)
from goldsignal.data.provider import get_data_provider
from goldsignal.data.validation import validate_candles
from goldsignal.logging_config import configure_logging
from goldsignal.persistence import db, signals_repo
from goldsignal.strategy.day_trade import DayTradeStrategy
from goldsignal.strategy.scalp import ScalpStrategy
from goldsignal.utils.time import utc_now

logger = logging.getLogger(__name__)

_MODE_BUILDERS = {
    "scalp": (load_scalp_config, ScalpStrategy),
    "daytrade": (load_daytrade_config, DayTradeStrategy),
}
_LIVE_LOOKBACK_CANDLES = 300


def _fetch_real_candles(settings: GlobalSettings, config, days: int):
    provider = get_data_provider(settings)
    end = utc_now()
    start = end - timedelta(days=days)
    entry_raw = provider.get_candles(settings.instrument, config.entry_timeframe, start, end)
    confirm_raw = provider.get_candles(
        settings.instrument, config.confirmation_timeframe, start, end
    )
    entry_result = validate_candles(entry_raw, config.entry_timeframe, end)
    confirm_result = validate_candles(confirm_raw, config.confirmation_timeframe, end)
    for issue in entry_result.issues + confirm_result.issues:
        logger.info("data validation: %s", issue)
    return entry_result.clean_candles, confirm_result.clean_candles


def _write_outputs(args, name: str, text: str, title: str) -> None:
    if not args.output_dir:
        return
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{name}.txt").write_text(text, encoding="utf-8")
    write_html_report(text, out / f"{name}.html", title=title)
    print(f"\nWrote {out / f'{name}.txt'} and {out / f'{name}.html'}")


def cmd_frequency(args, settings: GlobalSettings) -> None:
    config_loader, strategy_cls = _MODE_BUILDERS[args.mode]
    config = config_loader()
    strategy = strategy_cls(config, settings.instrument)
    entry, confirm = _fetch_real_candles(settings, config, args.days)
    report = analyze_frequency(
        strategy, entry, confirm, instrument=settings.instrument, split_ratio=args.split_ratio
    )
    text = format_frequency_report(report)
    print(text)
    _write_outputs(args, f"frequency_{args.mode}", text, f"GoldSignal frequency — {args.mode}")


def cmd_compare(args, settings: GlobalSettings) -> None:
    config_loader, strategy_cls = _MODE_BUILDERS[args.mode]
    config = config_loader()
    strategy = strategy_cls(config, settings.instrument)
    entry, confirm = _fetch_real_candles(settings, config, args.days)
    results = run_comparison(
        strategy_cls, strategy.mode, config, settings.instrument, entry, confirm
    )
    text = format_variant_comparison(results)
    print(text)
    _write_outputs(
        args, f"compare_{args.mode}", text, f"GoldSignal variant comparison — {args.mode}"
    )


def cmd_diagnostics(args, settings: GlobalSettings) -> None:
    config_loader, strategy_cls = _MODE_BUILDERS[args.mode]
    config = config_loader()
    strategy = strategy_cls(config, settings.instrument)
    now = utc_now()
    provider = get_data_provider(settings)
    entry_start = now - config.entry_timeframe.duration * _LIVE_LOOKBACK_CANDLES
    confirm_start = now - config.confirmation_timeframe.duration * _LIVE_LOOKBACK_CANDLES
    entry_raw = provider.get_candles(settings.instrument, config.entry_timeframe, entry_start, now)
    confirm_raw = provider.get_candles(
        settings.instrument, config.confirmation_timeframe, confirm_start, now
    )

    db_stats = None
    context = None
    if settings.database_url:
        conn = db.connect(settings.database_url)
        try:
            db.ensure_schema(conn)
            context = signals_repo.build_evaluation_context(
                conn, strategy_mode=strategy.mode.value, instrument=settings.instrument, now=now
            )
            db_stats = fetch_db_stats(
                conn, strategy_mode=strategy.mode.value, instrument=settings.instrument, now=now
            )
        finally:
            conn.close()
    else:
        logger.warning("GOLDSIGNAL_DATABASE_URL not set — skipping DB-backed history stats")

    snapshot = build_snapshot(
        strategy,
        entry_raw,
        confirm_raw,
        instrument=settings.instrument,
        now=now,
        context=context,
        db_stats=db_stats,
    )
    text = format_diagnostics_snapshot(snapshot)
    print(text)
    _write_outputs(args, f"diagnostics_{args.mode}", text, f"GoldSignal diagnostics — {args.mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    freq = sub.add_parser("frequency")
    freq.add_argument("--days", type=int, default=180)
    freq.add_argument("--split-ratio", type=float, default=0.7)
    freq.set_defaults(func=cmd_frequency)

    compare = sub.add_parser("compare")
    compare.add_argument("--days", type=int, default=180)
    compare.set_defaults(func=cmd_compare)

    diag = sub.add_parser("diagnostics")
    diag.set_defaults(func=cmd_diagnostics)

    for p in (freq, compare, diag):
        p.add_argument("--mode", choices=["scalp", "daytrade"], required=True)
        p.add_argument("--output-dir", default="analysis_output")

    args = parser.parse_args()
    load_dotenv()
    configure_logging("INFO")
    settings = load_global_settings()
    print(f"Data provider: {settings.data_provider}\n")
    args.func(args, settings)


if __name__ == "__main__":
    main()
