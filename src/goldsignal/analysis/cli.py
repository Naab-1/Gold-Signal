"""Signal diagnostics & frequency audit CLI.

Usage:
    python -m goldsignal.analysis.cli frequency --mode scalp --days 180
    python -m goldsignal.analysis.cli compare --mode scalp --days 180
    python -m goldsignal.analysis.cli compare-tiers --mode scalp --days 180
    python -m goldsignal.analysis.cli diagnostics --mode scalp
    python -m goldsignal.analysis.cli quotes

All use the real configured data provider (GOLDSIGNAL_DATA_PROVIDER
from .env) — this is a reporting/comparison tool, it never changes
production strategy settings. `quotes` is mode-independent and reports on
all configured instruments (XAU/USD, EUR/USD, GBP/USD, USD/JPY) — it does
not evaluate strategy rules or send any alert.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

from goldsignal.analysis.diagnostics import build_snapshot, fetch_db_stats
from goldsignal.analysis.frequency import analyze_frequency
from goldsignal.analysis.report import (
    format_diagnostics_snapshot,
    format_frequency_report,
    format_quotes_dashboard,
    format_tier_comparison,
    format_variant_comparison,
    write_html_report,
)
from goldsignal.analysis.tier_comparison import ALL_VARIANTS, VARIANT_A_PLUS, run_tier_comparison
from goldsignal.analysis.variants import run_comparison
from goldsignal.config import (
    GlobalSettings,
    load_daytrade_config,
    load_global_settings,
    load_scalp_config,
)
from goldsignal.data.provider import get_data_provider
from goldsignal.data.quote_validation import assess_quote
from goldsignal.data.twelvedata_provider import DataProviderError
from goldsignal.data.validation import validate_candles
from goldsignal.instruments import (
    INSTRUMENT_CODES,
    effective_mode_config,
    load_all_instrument_profiles,
    load_instrument_profile,
)
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


@dataclasses.dataclass
class FetchedCandles:
    instrument: str
    entry: list
    confirm: list
    issues: list[str]
    start: object
    end: object


def _fetch_real_candles_detailed(
    settings: GlobalSettings, config, days: int, *, instrument: str | None = None
) -> FetchedCandles:
    provider = get_data_provider(settings)
    target_instrument = instrument or settings.instrument
    end = utc_now()
    start = end - timedelta(days=days)
    entry_raw = provider.get_candles(target_instrument, config.entry_timeframe, start, end)
    confirm_raw = provider.get_candles(target_instrument, config.confirmation_timeframe, start, end)
    entry_result = validate_candles(entry_raw, config.entry_timeframe, end)
    confirm_result = validate_candles(confirm_raw, config.confirmation_timeframe, end)
    issues = entry_result.issues + confirm_result.issues
    for issue in issues:
        logger.info("data validation: %s", issue)
    return FetchedCandles(
        instrument=target_instrument,
        entry=entry_result.clean_candles,
        confirm=confirm_result.clean_candles,
        issues=issues,
        start=start,
        end=end,
    )


def _fetch_real_candles(settings: GlobalSettings, config, days: int):
    fetched = _fetch_real_candles_detailed(settings, config, days)
    return fetched.entry, fetched.confirm


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


def cmd_compare_tiers(args, settings: GlobalSettings) -> None:
    config_loader, strategy_cls = _MODE_BUILDERS[args.mode]
    config = config_loader()

    # Omitting --instrument takes the exact existing code path (settings.instrument,
    # config unmodified) so today's XAU/USD behavior can never change here. An
    # explicit, different --instrument resolves its profile and overlays only the
    # profile's cost fields onto config via effective_mode_config -- see instruments.py.
    instrument = settings.instrument
    if args.instrument and args.instrument != settings.instrument:
        instrument = args.instrument
        profile = load_instrument_profile(instrument)
        config = effective_mode_config(config, profile)

    strategy = strategy_cls(config, instrument)
    fetched = _fetch_real_candles_detailed(settings, config, args.days, instrument=instrument)
    variants = ALL_VARIANTS if args.variants == "all" else (VARIANT_A_PLUS,)
    report = run_tier_comparison(
        strategy,
        strategy.mode,
        strategy.version,
        config,
        instrument,
        fetched.entry,
        fetched.confirm,
        split_ratio=args.split_ratio,
        variants=variants,
    )

    data_quality_lines = [
        f"=== Data: {instrument} via {settings.data_provider} ===",
        f"Period: {fetched.start.isoformat()} -> {fetched.end.isoformat()}",
        f"Entry candles (after cleaning): {len(fetched.entry)}",
        f"Confirmation candles (after cleaning): {len(fetched.confirm)}",
        f"Validation issues (gaps/duplicates/malformed/stale, see log for detail): "
        f"{len(fetched.issues)}",
        "",
    ]
    text = "\n".join(data_quality_lines) + format_tier_comparison(report)
    print(text)
    _write_outputs(
        args,
        f"compare_tiers_{args.mode}_{instrument}",
        text,
        f"GoldSignal tier comparison — {args.mode} — {instrument}",
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


def _parse_broker_price_arg(raw: str) -> tuple[str, float]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"expected CODE=PRICE, got {raw!r}")
    code, _, price_raw = raw.partition("=")
    code = code.strip().upper()
    if code not in INSTRUMENT_CODES:
        raise argparse.ArgumentTypeError(
            f"unknown instrument {code!r} in {raw!r}; expected one of {INSTRUMENT_CODES}"
        )
    try:
        price = float(price_raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"price must be a number in {raw!r}") from exc
    return code, price


def cmd_quotes(args, settings: GlobalSettings) -> None:
    provider = get_data_provider(settings)
    profiles = load_all_instrument_profiles()
    broker_prices = dict(args.broker_price)
    now = utc_now()

    rows = []
    for code in INSTRUMENT_CODES:
        profile = profiles[code]
        try:
            quote = provider.get_quote(profile.provider_symbol)
        except DataProviderError as exc:
            logger.warning("quote unavailable for %s: %s", code, exc)
            rows.append((profile, None, str(exc)))
            continue
        assessment = assess_quote(
            quote,
            profile,
            now,
            max_quote_age=timedelta(seconds=args.max_quote_age_seconds),
            broker_price=broker_prices.get(code),
            broker_tolerance=args.broker_tolerance,
        )
        rows.append((profile, assessment, None))

    text = format_quotes_dashboard(rows, now=now)
    print(text)
    _write_outputs(args, "quotes", text, "GoldSignal instrument quotes")


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

    compare_tiers = sub.add_parser("compare-tiers")
    compare_tiers.add_argument("--days", type=int, default=180)
    compare_tiers.add_argument("--split-ratio", type=float, default=0.7)
    compare_tiers.add_argument(
        "--instrument",
        choices=list(INSTRUMENT_CODES),
        default=None,
        help="Defaults to GOLDSIGNAL_INSTRUMENT (today's XAU/USD path, unmodified). "
        "A different value backtests that instrument via its profile's cost settings.",
    )
    compare_tiers.add_argument(
        "--variants",
        choices=["all", "a-plus"],
        default="all",
        help="'a-plus' skips the experimental two-candle/one-candle A-tier walks -- "
        "use this for instruments where only the A+ baseline has been requested.",
    )
    compare_tiers.set_defaults(func=cmd_compare_tiers)

    diag = sub.add_parser("diagnostics")
    diag.set_defaults(func=cmd_diagnostics)

    for p in (freq, compare, compare_tiers, diag):
        p.add_argument("--mode", choices=["scalp", "daytrade"], required=True)
        p.add_argument("--output-dir", default="analysis_output")

    quotes = sub.add_parser("quotes")
    quotes.add_argument("--max-quote-age-seconds", type=int, default=120)
    quotes.add_argument(
        "--broker-price",
        action="append",
        type=_parse_broker_price_arg,
        default=[],
        metavar="CODE=PRICE",
        help="e.g. --broker-price EURUSD=1.0850 (repeatable)",
    )
    quotes.add_argument(
        "--broker-tolerance",
        type=float,
        default=None,
        help="Overrides every instrument's own broker_price_tolerance for this run",
    )
    quotes.add_argument("--output-dir", default="analysis_output")
    quotes.set_defaults(func=cmd_quotes)

    args = parser.parse_args()
    load_dotenv()
    configure_logging("INFO")
    settings = load_global_settings()
    print(f"Data provider: {settings.data_provider}\n")
    args.func(args, settings)


if __name__ == "__main__":
    main()
