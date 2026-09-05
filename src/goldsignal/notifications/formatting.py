"""Telegram message text for a StrategySignal.

Kept short and readable without trading jargon, per the requirement that
alerts work on mobile/limited bandwidth and don't assume advanced trading
knowledge. GHS conversion is intentionally not included yet — it needs a
configured account balance/currency and a live, timestamped FX rate,
neither of which exist until Phase 4.
"""

from __future__ import annotations

from goldsignal.models.signal import SignalDirection, StrategyMode, StrategySignal
from goldsignal.notifications.sessions import session_label, to_accra_time

DISCLAIMER = "Paper-trading/research signal — not financial advice"

_MODE_LABELS = {
    StrategyMode.SCALP: "SCALP",
    StrategyMode.DAY_TRADE: "DAY TRADE",
    StrategyMode.TREND_PULLBACK: "TREND PULLBACK",
    StrategyMode.BREAKOUT_CONTINUATION: "BREAKOUT CONTINUATION",
    StrategyMode.BREAKOUT_AND_RETEST: "BREAKOUT AND RETEST",
}
_DIRECTION_EMOJI = {
    SignalDirection.BUY: "🟢",
    SignalDirection.SELL: "🔴",
}


def _time_lines(signal: StrategySignal) -> str:
    accra = to_accra_time(signal.signal_timestamp)
    utc_str = signal.signal_timestamp.strftime("%H:%M UTC")
    try:
        accra_str = accra.strftime("%-I:%M %p")  # e.g. "2:00 PM" (no leading zero)
    except ValueError:
        accra_str = accra.strftime("%I:%M %p").lstrip("0")  # Windows has no "-" flag
    return f"Time: {accra_str} Ghana | {utc_str}"


def format_trade_signal(signal: StrategySignal) -> str:
    if signal.direction not in (SignalDirection.BUY, SignalDirection.SELL):
        raise ValueError("format_trade_signal is only for BUY/SELL signals")

    mode = _MODE_LABELS[signal.strategy_mode]
    emoji = _DIRECTION_EMOJI[signal.direction]
    lines = [
        f"{emoji} {mode} {signal.direction.value} — {signal.instrument}",
        _time_lines(signal),
        f"Entry: {signal.entry_price:,.2f}",
        f"Stop: {signal.stop_loss:,.2f}",
    ]
    for target in signal.targets:
        lines.append(f"{target.label}: {target.price:,.2f} ({target.r_multiple:.1f}R)")
    lines.append(f"Session: {session_label(signal.signal_timestamp)}")
    lines.append(f"Reason: {signal.reason}")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def format_missed_setup(signal: StrategySignal, *, reason: str, delay: str) -> str:
    """A distinct message shape from `format_trade_signal` — this must
    never be mistaken for a live, actionable entry.
    """
    mode = _MODE_LABELS[signal.strategy_mode]
    lines = [
        f"⚠️ SETUP DETECTED LATE — DO NOT ENTER ({mode}, {signal.instrument})",
        _time_lines(signal),
        f"Original setup: {signal.direction.value} @ {signal.entry_price:,.2f}",
        f"Reason no longer actionable: {reason}",
        f"Detected {delay} after it formed — too late to act on.",
        "",
        DISCLAIMER,
    ]
    return "\n".join(lines)


def format_health_alert(*, strategy_mode_label: str, gap: str) -> str:
    return (
        f"🛑 SYSTEM HEALTH — {strategy_mode_label}\n"
        f"No successful scan in {gap}.\n"
        "This is a system status notice, not a trading signal — no action needed on price."
    )


def format_recovery_alert(*, strategy_mode_label: str, gap: str) -> str:
    return (
        f"✅ SYSTEM RECOVERED — {strategy_mode_label}\n"
        f"Scanning resumed after a {gap} gap; any missed candles have been processed.\n"
        "This is a system status notice, not a trading signal."
    )


def format_no_trade_signal(signal: StrategySignal) -> str:
    if signal.direction != SignalDirection.NO_TRADE:
        raise ValueError("format_no_trade_signal is only for NO_TRADE signals")

    mode = _MODE_LABELS[signal.strategy_mode]
    lines = [
        f"{mode} NO_TRADE — {signal.instrument}",
        _time_lines(signal),
        f"Reason: {signal.reason}",
    ]
    if signal.conditions_failed:
        lines.append(f"Conditions failed: {', '.join(signal.conditions_failed)}")
    lines.append("")
    lines.append(DISCLAIMER)
    return "\n".join(lines)
