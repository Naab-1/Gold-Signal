"""Send a StrategySignal to Telegram.

Telegram is the primary and only alert channel — chosen for mobile-first,
low-bandwidth use. NO_TRADE signals are never sent unless
GOLDSIGNAL_TELEGRAM_DEBUG_MODE=true. Never logs the bot token.
"""

from __future__ import annotations

import logging

import requests

from goldsignal.models.signal import SignalDirection, StrategySignal
from goldsignal.notifications.formatting import format_no_trade_signal, format_trade_signal

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramError(RuntimeError):
    """Raised when Telegram rejects or fails to deliver a message."""


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
    if not bot_token or not chat_id:
        raise ValueError("bot_token and chat_id must both be configured")

    if signal.direction == SignalDirection.NO_TRADE:
        if not debug_mode:
            return False
        text = format_no_trade_signal(signal)
    else:
        text = format_trade_signal(signal)

    url = _API_URL.format(token=bot_token)
    response = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)

    if response.status_code != 200:
        raise TelegramError(f"Telegram send failed with HTTP {response.status_code}")

    body = response.json()
    if not body.get("ok"):
        raise TelegramError(f"Telegram rejected the message: {body.get('description')}")

    logger.info(
        "sent Telegram alert mode=%s direction=%s",
        signal.strategy_mode.value,
        signal.direction.value,
    )
    return True
