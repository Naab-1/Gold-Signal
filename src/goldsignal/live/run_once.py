"""Manual one-shot live run: fetch real candles, evaluate, persist, alert.

Not a scheduler — run this by hand (or wire an external cron to it later)
to verify the full pipeline against real credentials:

    python -m goldsignal.live.run_once --mode scalp

The actual recurring scheduler is Phase 4.
"""

from __future__ import annotations

import argparse
import logging

from dotenv import load_dotenv

from goldsignal.config import load_daytrade_config, load_global_settings, load_scalp_config
from goldsignal.data.provider import get_data_provider
from goldsignal.data.validation import validate_candles
from goldsignal.logging_config import configure_logging
from goldsignal.models.signal import SignalDirection
from goldsignal.notifications.telegram import send_signal_alert
from goldsignal.persistence import db, signals_repo
from goldsignal.strategy.day_trade import DayTradeStrategy
from goldsignal.strategy.scalp import ScalpStrategy
from goldsignal.utils.time import utc_now

logger = logging.getLogger(__name__)

_MODE_BUILDERS = {
    "scalp": (load_scalp_config, ScalpStrategy),
    "daytrade": (load_daytrade_config, DayTradeStrategy),
}
_LOOKBACK_CANDLES = 300


def run_once(mode_key: str) -> None:
    settings = load_global_settings()
    config_loader, strategy_cls = _MODE_BUILDERS[mode_key]
    config = config_loader()
    if not config.enabled:
        logger.info("mode=%s is disabled, skipping", mode_key)
        return

    provider = get_data_provider(settings)
    strategy = strategy_cls(config, settings.instrument)
    now = utc_now()

    entry_start = now - config.entry_timeframe.duration * _LOOKBACK_CANDLES
    confirm_start = now - config.confirmation_timeframe.duration * _LOOKBACK_CANDLES
    entry_raw = provider.get_candles(settings.instrument, config.entry_timeframe, entry_start, now)
    confirm_raw = provider.get_candles(
        settings.instrument, config.confirmation_timeframe, confirm_start, now
    )

    entry_result = validate_candles(entry_raw, config.entry_timeframe, now)
    confirm_result = validate_candles(confirm_raw, config.confirmation_timeframe, now)
    for issue in entry_result.issues + confirm_result.issues:
        logger.info("data validation: %s", issue)

    if not entry_result.is_usable or not confirm_result.is_usable:
        logger.warning("mode=%s rejecting evaluation: stale or insufficient data", mode_key)
        return

    conn = db.connect(settings.database_url)
    try:
        db.ensure_schema(conn)
        context = signals_repo.build_evaluation_context(
            conn, strategy_mode=strategy.mode.value, instrument=settings.instrument, now=now
        )
        signal = strategy.evaluate(
            entry_result.clean_candles, confirm_result.clean_candles, now=now, context=context
        )

        if signal.direction != SignalDirection.NO_TRADE:
            fingerprint = signals_repo.fingerprint_of(signal)
            last = signals_repo.get_last_trade_signal(
                conn, strategy_mode=strategy.mode.value, instrument=settings.instrument
            )
            if signals_repo.is_duplicate(fingerprint, last):
                logger.info("mode=%s duplicate of the last signal, not re-alerting", mode_key)
                signals_repo.save_signal(conn, signal)
                return

        signals_repo.save_signal(conn, signal)

        if settings.telegram_bot_token and settings.telegram_chat_id:
            send_signal_alert(
                signal,
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
                debug_mode=settings.telegram_debug_mode,
            )
        else:
            logger.warning("Telegram not configured (GOLDSIGNAL_TELEGRAM_*), skipping alert")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["scalp", "daytrade"], required=True)
    args = parser.parse_args()
    load_dotenv()
    configure_logging("INFO")
    run_once(args.mode)


if __name__ == "__main__":
    main()
