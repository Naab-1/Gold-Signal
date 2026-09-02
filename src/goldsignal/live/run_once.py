"""Durable, gap-tolerant live scan: catch up on every closed candle since
the last successful run, evaluate each exactly once, and alert on it
exactly once — rather than only ever looking at "right now."

Why this exists: GitHub Actions' `schedule:` cron does not reliably fire
every 5/15 minutes (confirmed in practice — a real ~4h43m gap was
observed between two "every 15 minutes" runs). The old single-candle
`run_once` had no way to notice or recover from that: it only ever asked
"is there a signal right now?", so a setup that formed and completed
entirely inside a scheduler gap was silently gone forever. This version
persists a per-(strategy, version, timeframe, provider, instrument)
checkpoint (`persistence.checkpoints_repo`) and walks every closed candle
after it, oldest first, so a gap of any length gets fully caught up on
the next run rather than skipped.

Continue sending only the existing A+ tier to Telegram — the A/WATCHLIST
classification work is not wired to live alerts here or anywhere else.

    python -m goldsignal.live.run_once --mode scalp
"""

from __future__ import annotations

import argparse
import logging
from datetime import timedelta

from dotenv import load_dotenv

from goldsignal.config import (
    GlobalSettings,
    ModeConfig,
    load_daytrade_config,
    load_global_settings,
    load_scalp_config,
)
from goldsignal.data.provider import DataProvider, get_data_provider
from goldsignal.data.validation import validate_candles
from goldsignal.live import health
from goldsignal.live.catchup import DEFAULT_LOOKBACK_CANDLES, iter_unprocessed_candles
from goldsignal.logging_config import configure_logging
from goldsignal.models.signal import SignalDirection, StrategySignal
from goldsignal.notifications.telegram import (
    TelegramError,
    send_health_alert,
    send_missed_setup_alert,
    send_recovery_alert,
    send_signal_alert,
)
from goldsignal.persistence import checkpoints_repo, db, health_repo, signals_repo
from goldsignal.persistence.checkpoints_repo import CheckpointKey
from goldsignal.strategy.actionability import is_still_actionable
from goldsignal.strategy.base import EvaluationContext, Strategy
from goldsignal.strategy.day_trade import DayTradeStrategy
from goldsignal.strategy.scalp import ScalpStrategy
from goldsignal.utils.time import floor_to_duration, format_timedelta, utc_now

logger = logging.getLogger(__name__)

_MODE_BUILDERS = {
    "scalp": (load_scalp_config, ScalpStrategy),
    "daytrade": (load_daytrade_config, DayTradeStrategy),
}
_MISSED_LOOKBACK_FOR_HEALTH = timedelta(hours=24)


def _checkpoint_key(
    settings: GlobalSettings, config: ModeConfig, strategy: Strategy
) -> CheckpointKey:
    return CheckpointKey(
        strategy_mode=strategy.mode.value,
        strategy_version=strategy.version,
        entry_timeframe=config.entry_timeframe.value,
        data_provider=settings.data_provider,
        instrument=settings.instrument,
    )


def _handle_evaluated_signal(
    conn,
    settings: GlobalSettings,
    signal: StrategySignal,
    *,
    is_late: bool,
    latest_price: float,
    wall_clock_now,
) -> None:
    signals_repo.save_signal(conn, signal, detected_late=is_late)

    if signal.direction == SignalDirection.NO_TRADE:
        return

    fingerprint = signals_repo.fingerprint_of(signal)
    last = signals_repo.get_last_trade_signal(
        conn, strategy_mode=signal.strategy_mode.value, instrument=signal.instrument
    )
    if signals_repo.is_duplicate(fingerprint, last):
        logger.info(
            "mode=%s duplicate of the last stored trade idea, not alerting",
            signal.strategy_mode.value,
        )
        return

    actionable, reason = is_still_actionable(signal, now=wall_clock_now, latest_price=latest_price)
    if not actionable:
        signals_repo.mark_missed(conn, signal.signal_id, reason=reason)
        logger.warning(
            "mode=%s signal_id=%s MISSED_DURING_SCHEDULER_GAP: %s",
            signal.strategy_mode.value,
            signal.signal_id,
            reason,
        )
        if settings.telegram_bot_token and settings.telegram_chat_id:
            delay = format_timedelta(wall_clock_now - signal.signal_timestamp)
            send_missed_setup_alert(
                signal,
                reason=reason,
                delay=delay,
                bot_token=settings.telegram_bot_token,
                chat_id=settings.telegram_chat_id,
            )
        return

    if not (settings.telegram_bot_token and settings.telegram_chat_id):
        logger.warning("Telegram not configured (GOLDSIGNAL_TELEGRAM_*), skipping alert")
        return

    claimed = signals_repo.claim_telegram_send(conn, signal.signal_id)
    if not claimed:
        logger.info(
            "mode=%s signal_id=%s Telegram alert already sent, skipping (idempotent retry)",
            signal.strategy_mode.value,
            signal.signal_id,
        )
        return

    try:
        send_signal_alert(
            signal,
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            debug_mode=settings.telegram_debug_mode,
        )
    except TelegramError:
        signals_repo.unclaim_telegram_send(conn, signal.signal_id)
        raise


def _run_catchup(
    conn,
    settings: GlobalSettings,
    config: ModeConfig,
    strategy: Strategy,
    provider: DataProvider,
    wall_clock_now,
) -> int:
    key = _checkpoint_key(settings, config, strategy)
    checkpoint = checkpoints_repo.get_checkpoint(conn, key)

    fetch_anchor = checkpoint if checkpoint is not None else wall_clock_now
    entry_start = fetch_anchor - config.entry_timeframe.duration * DEFAULT_LOOKBACK_CANDLES
    confirm_start = fetch_anchor - config.confirmation_timeframe.duration * DEFAULT_LOOKBACK_CANDLES

    entry_raw = provider.get_candles(
        settings.instrument, config.entry_timeframe, entry_start, wall_clock_now
    )
    confirm_raw = provider.get_candles(
        settings.instrument, config.confirmation_timeframe, confirm_start, wall_clock_now
    )

    entry_result = validate_candles(entry_raw, config.entry_timeframe, wall_clock_now)
    confirm_result = validate_candles(confirm_raw, config.confirmation_timeframe, wall_clock_now)
    for issue in entry_result.issues + confirm_result.issues:
        logger.info("data validation: %s", issue)

    if not entry_result.is_usable or not confirm_result.is_usable:
        logger.warning(
            "mode=%s rejecting evaluation: stale or insufficient data", strategy.mode.value
        )
        return 0

    context = signals_repo.build_evaluation_context(
        conn, strategy_mode=strategy.mode.value, instrument=settings.instrument, now=wall_clock_now
    )

    processed_count = 0
    for item in iter_unprocessed_candles(
        entry_result.clean_candles,
        confirm_result.clean_candles,
        entry_duration=config.entry_timeframe.duration,
        confirm_duration=config.confirmation_timeframe.duration,
        checkpoint=checkpoint,
        now=wall_clock_now,
    ):
        signal = strategy.evaluate(
            item.entry_window, item.confirmation_window, now=item.close_time, context=context
        )
        try:
            _handle_evaluated_signal(
                conn,
                settings,
                signal,
                is_late=item.is_late,
                latest_price=item.entry_window[-1].close,
                wall_clock_now=wall_clock_now,
            )
        except Exception:
            logger.exception(
                "mode=%s failed processing candle close_time=%s -- stopping catch-up here; "
                "checkpoint stays at the last successfully processed candle",
                strategy.mode.value,
                item.close_time,
            )
            break

        checkpoints_repo.set_checkpoint(conn, key, item.close_time)
        checkpoint = item.close_time
        processed_count += 1

        if signal.direction != SignalDirection.NO_TRADE:
            context = EvaluationContext(
                last_signal_time=signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )

    return processed_count


def _check_health_and_alert(
    conn,
    settings: GlobalSettings,
    config: ModeConfig,
    strategy: Strategy,
    wall_clock_now,
) -> None:
    key = _checkpoint_key(settings, config, strategy)
    last_processed = checkpoints_repo.get_checkpoint(conn, key)
    last_success = health_repo.get_last_successful_run_at(
        conn, strategy_mode=strategy.mode.value, strategy_version=strategy.version
    )
    missed_count = signals_repo.count_missed_since(
        conn,
        strategy_mode=strategy.mode.value,
        instrument=settings.instrument,
        since=wall_clock_now - _MISSED_LOOKBACK_FOR_HEALTH,
    )
    expected_latest_closed = floor_to_duration(wall_clock_now, config.entry_timeframe.duration)

    snapshot = health.evaluate_health(
        strategy_mode=strategy.mode.value,
        now=wall_clock_now,
        last_successful_run_at=last_success,
        last_processed_candle=last_processed,
        expected_latest_closed_candle=expected_latest_closed,
        entry_duration=config.entry_timeframe.duration,
        missed_setups_recent_count=missed_count,
    )

    alert_state = health_repo.get_alert_state(
        conn, strategy_mode=strategy.mode.value, strategy_version=strategy.version
    )
    action = health.decide_alert_action(snapshot, previously_healthy=alert_state.is_healthy)

    if (
        action != health.AlertAction.NONE
        and settings.telegram_bot_token
        and settings.telegram_chat_id
    ):
        gap_str = (
            format_timedelta(snapshot.gap_since_last_success)
            if snapshot.gap_since_last_success is not None
            else "unknown"
        )
        label = f"{strategy.mode.value} ({strategy.version})"
        try:
            if action == health.AlertAction.SEND_HEALTH_ALERT:
                send_health_alert(
                    strategy_mode_label=label,
                    gap=gap_str,
                    bot_token=settings.telegram_bot_token,
                    chat_id=settings.telegram_chat_id,
                )
            else:
                send_recovery_alert(
                    strategy_mode_label=label,
                    gap=gap_str,
                    bot_token=settings.telegram_bot_token,
                    chat_id=settings.telegram_chat_id,
                )
        except TelegramError:
            logger.exception(
                "mode=%s failed to send scheduler health/recovery notice", strategy.mode.value
            )

    unhealthy_since = alert_state.unhealthy_since
    if snapshot.is_healthy:
        unhealthy_since = None
    elif alert_state.is_healthy:
        unhealthy_since = wall_clock_now

    health_repo.set_alert_state(
        conn,
        strategy_mode=strategy.mode.value,
        strategy_version=strategy.version,
        is_healthy=snapshot.is_healthy,
        unhealthy_since=unhealthy_since,
    )


def run_once(mode_key: str) -> None:
    settings = load_global_settings()
    config_loader, strategy_cls = _MODE_BUILDERS[mode_key]
    config = config_loader()
    if not config.enabled:
        logger.info("mode=%s is disabled, skipping", mode_key)
        return

    provider = get_data_provider(settings)
    strategy = strategy_cls(config, settings.instrument)
    wall_clock_now = utc_now()

    conn = db.connect(settings.database_url)
    try:
        db.ensure_schema(conn)
        run_id = health_repo.record_run_start(
            conn,
            strategy_mode=strategy.mode.value,
            strategy_version=strategy.version,
            started_at=wall_clock_now,
        )

        succeeded = False
        error_message: str | None = None
        candles_processed = 0
        try:
            candles_processed = _run_catchup(
                conn, settings, config, strategy, provider, wall_clock_now
            )
            succeeded = True
        except Exception as exc:
            error_message = str(exc)
            raise
        finally:
            health_repo.record_run_finish(
                conn,
                run_id,
                finished_at=utc_now(),
                succeeded=succeeded,
                candles_processed=candles_processed,
                error_message=error_message,
            )
            _check_health_and_alert(conn, settings, config, strategy, wall_clock_now)
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
