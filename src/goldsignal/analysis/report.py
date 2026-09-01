"""Renders FrequencyReport / VariantResult / DiagnosticsSnapshot as plain
text (always) and a self-contained local HTML file (no server — matching
backtest_output/'s pattern of writing files to open directly).
"""

from __future__ import annotations

import html
from pathlib import Path

from goldsignal.analysis.diagnostics import DiagnosticsSnapshot
from goldsignal.analysis.frequency import FrequencyReport
from goldsignal.analysis.variants import VariantResult


def format_frequency_report(report: FrequencyReport) -> str:
    lines = [f"=== Frequency report: {report.mode} ===", ""]
    lines.append(f"Total candles evaluated: {report.total_candles}")
    lines.append("")
    lines.append("Funnel:")
    for stage, count in report.funnel.items():
        lines.append(f"  {stage:20s} {count}")
    lines.append("")
    lines.append("Rejections by individual filter:")
    for name, count in sorted(report.rejection_counts_single.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {name:30s} {count}")
    lines.append("")
    lines.append("Rejections by combination of filters:")
    for combo, count in sorted(report.rejection_combinations.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {combo:60s} {count}")
    lines.append("")
    lines.append(
        f"Near-misses (exactly one blocking condition, most recent {len(report.near_misses)}):"
    )
    for nm in report.near_misses[-10:]:
        lines.append(
            f"  {nm['timestamp']}  blocked by {nm['blocking_condition']} "
            f"(candidate={nm['candidate_direction']})"
        )
    lines.append("")
    lines.append(f"Signals by session: {report.signals_by_session}")
    lines.append(f"Signals by weekday: {report.signals_by_weekday}")
    lines.append(f"Max consecutive no-signal scans: {report.max_consecutive_no_signal}")
    lines.append(f"Development signals: {report.development_signal_count}")
    lines.append(f"Out-of-sample signals: {report.out_of_sample_signal_count}")
    lines.append(
        f"Signals if costs were zero: {report.signals_without_cost_filter} "
        f"(vs {report.funnel['final_signals']} with real costs)"
    )
    return "\n".join(lines)


def format_variant_comparison(results: list[VariantResult]) -> str:
    lines = ["=== Variant comparison (informational only — no settings changed) ===", ""]
    header = (
        f"{'variant':24s} {'trades':>7s} {'trades/day':>11s} {'expectancy_r':>13s} "
        f"{'profit_factor':>14s} {'max_dd_r':>9s} {'max_losses':>11s}"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for r in results:
        pf = "n/a" if r.summary.profit_factor is None else f"{r.summary.profit_factor:.2f}"
        lines.append(
            f"{r.variant_name:24s} {r.total_trades:7d} {r.trades_per_day:11.2f} "
            f"{r.summary.expectancy_r:+13.3f} {pf:>14s} {r.summary.max_drawdown_r:9.2f} "
            f"{r.summary.max_consecutive_losses:11d}"
        )
    return "\n".join(lines)


def format_diagnostics_snapshot(snap: DiagnosticsSnapshot) -> str:
    lines = [f"=== Live diagnostics: {snap.mode} ===", ""]
    lines.append(f"Now (UTC):                 {snap.now.isoformat()}")
    lines.append(f"Latest completed candle:   {snap.latest_completed_candle}")
    lines.append(f"Feed delay:                {snap.feed_delay}")
    lines.append(f"Data stale:                {snap.is_stale}")
    lines.append(f"Current session:           {snap.current_session}")
    lines.append(f"Next scheduled scan (est): {snap.next_scheduled_scan.isoformat()}")
    lines.append(f"Stage reached:             {snap.stage}")
    lines.append(f"Final reason:              {snap.final_reason}")
    lines.append(f"Near-miss condition:       {snap.near_miss_condition}")
    lines.append("Conditions:")
    for name, ok in snap.conditions.items():
        lines.append(f"  {name:30s} {'PASS' if ok else 'FAIL'}")
    if snap.db_stats:
        d = snap.db_stats
        lines.append("")
        lines.append(f"Latest scan in DB:         {d.latest_scan_timestamp}")
        lines.append(
            f"Signals last 24h / 7d / 30d: "
            f"{d.signals_last_24h} / {d.signals_last_7d} / {d.signals_last_30d}"
        )
        lines.append(f"Consecutive no-signal scans: {d.consecutive_no_signal_scans}")
    return "\n".join(lines)


def write_html_report(
    text_report: str, path: str | Path, *, title: str = "GoldSignal diagnostics"
) -> None:
    body = html.escape(text_report)
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
body {{ font-family: -apple-system, Segoe UI, sans-serif; background:#0b0f14;
  color:#e6edf3; padding:24px; }}
pre {{ background:#111820; padding:16px; border-radius:8px;
  overflow-x:auto; line-height:1.5; }}
h1 {{ font-size:18px; }}
</style></head>
<body><h1>{html.escape(title)}</h1><pre>{body}</pre></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
