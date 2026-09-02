"""Send a StrategySignal (or a system-status notice) to Telegram.

Telegram is the primary and only alert channel — chosen for mobile-first,
low-bandwidth use. NO_TRADE signals are never sent unless
GOLDSIGNAL_TELEGRAM_DEBUG_MODE=true. Never logs the bot token.

System-health/recovery/missed-setup notices use their own send functions
(not `send_signal_alert`) so they can never be confused with a trading
signal at the call site, on top of their distinct message formatting.
"""

from __future__ import annotations

import logging

import requests

from goldsignal.models.signal import SignalDirection, StrategySignal
from goldsignal.notifications.formatting import (
    format_health_alert,
    format_missed_setup,
    format_no_trade_signal,
    format_recovery_alert,
    format_trade_signal,
)

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramError(RuntimeError):
    """Raised when Telegram rejects or fails to deliver a message."""


def _send_text(text: str, *, bot_token: str, chat_id: str) -> None:
    if not bot_token or not chat_id:
        raise ValueError("bot_token and chat_id must both be configured")

    url = _API_URL.format(token=bot_token)
    response = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)

    if response.status_code != 200:
        raise TelegramError(f"Telegram send failed with HTTP {response.status_code}")

    body = response.json()
    if not body.get("ok"):
        raise TelegramError(f"Telegram rejected the message: {body.get('description')}")


def send_signal_alert(
    signal: StrategySignal,
    *,
    bot_token: str,
    chat_id: str,
    debug_mode: bool = False,
) -> bool:
    """Send `signal` to Telegram. Returns False (no send attempted) for a
    NO_TRADE signal unless `debug_mode` is True. Raises TelegramError on
    any delivery failure — callers must not swallow this silently.
    """
    if signal.direction == SignalDirection.NO_TRADE:
        if not debug_mode:
            return False
        text = format_no_trade_signal(signal)
    else:
        text = format_trade_signal(signal)

    _send_text(text, bot_token=bot_token, chat_id=chat_id)
    logger.info(
        "sent Telegram alert mode=%s direction=%s",
        signal.strategy_mode.value,
        signal.direction.value,
    )
    return True


def send_missed_setup_alert(
    signal: StrategySignal, *, reason: str, delay: str, bot_token: str, chat_id: str
) -> None:
    text = format_missed_setup(signal, reason=reason, delay=delay)
    _send_text(text, bot_token=bot_token, chat_id=chat_id)
    logger.info("sent missed-setup notice mode=%s", signal.strategy_mode.value)


def send_health_alert(*, strategy_mode_label: str, gap: str, bot_token: str, chat_id: str) -> None:
    text = format_health_alert(strategy_mode_label=strategy_mode_label, gap=gap)
    _send_text(text, bot_token=bot_token, chat_id=chat_id)
    logger.warning("sent scheduler health alert mode=%s gap=%s", strategy_mode_label, gap)


def send_recovery_alert(
    *, strategy_mode_label: str, gap: str, bot_token: str, chat_id: str
) -> None:
    text = format_recovery_alert(strategy_mode_label=strategy_mode_label, gap=gap)
    _send_text(text, bot_token=bot_token, chat_id=chat_id)
    logger.info("sent scheduler recovery notice mode=%s gap=%s", strategy_mode_label, gap)
