"""Walk-forward signal generation and trade-management simulation.

Two stages, deliberately kept separate (see plan): signal generation
(entry/stop/targets) never depends on the trade-management preset, so it
runs once per mode; only post-entry management is simulated per preset.
"""

from __future__ import annotations

import bisect
from datetime import date, datetime

from goldsignal.backtest.models import BacktestTrade, OpenedTrade, StopAdjustment, TargetFill
from goldsignal.config import ModeConfig
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategySignal
from goldsignal.strategy.base import EvaluationContext, Strategy
from goldsignal.strategy.trade_management import (
    BreakevenRule,
    BreakevenTrigger,
    TpShortfallHandling,
    TradeManagementPreset,
    resolve_allocations,
)


def entry_fill_price(signal: StrategySignal, fill_candle: Candle, config: ModeConfig) -> float:
    """Fill at the next candle's open, moved against the trader by half the
    spread plus slippage (transaction cost is applied once at trade close,
    not as a price-level adjustment). Public: shared by the walk-forward
    engine and the tier-comparison harness (`analysis/tier_comparison.py`),
    so both simulate fills identically.
    """
    adverse = config.estimated_spread / 2 + config.estimated_slippage
    if signal.direction == SignalDirection.BUY:
        return fill_candle.open + adverse
    return fill_candle.open - adverse


def gapped_through_stop(direction: SignalDirection, fill_price: float, stop_loss: float) -> bool:
    if direction == SignalDirection.BUY:
        return fill_price <= stop_loss
    return fill_price >= stop_loss


def generate_signals_walk_forward(
    strategy: Strategy,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    *,
    min_entry_index: int = 1,
) -> list[OpenedTrade]:
    """Walk `entry_candles` in order, evaluating the strategy at each closed
    candle using only data available up to that point (no look-ahead), and
    fill every BUY/SELL at the *next* candle's open. Maintains a real
    EvaluationContext so cooldown/session-limits are actually exercised.
    """
    config = strategy.config
    entry_duration = config.entry_timeframe.duration
    confirm_duration = config.confirmation_timeframe.duration
    confirm_close_times = [c.timestamp + confirm_duration for c in confirmation_candles]

    context = EvaluationContext()
    session_date: date | None = None
    opened: list[OpenedTrade] = []

    # Need i+1 to exist as the fill candle, so stop one short of the end.
    for i in range(min_entry_index, len(entry_candles) - 1):
        signal_candle = entry_candles[i]
        as_of = signal_candle.timestamp + entry_duration

        current_date = as_of.date()
        if session_date != current_date:
            session_date = current_date
            context = EvaluationContext(last_signal_time=context.last_signal_time)

        confirm_idx = bisect.bisect_right(confirm_close_times, as_of)
        confirm_window = confirmation_candles[:confirm_idx]

        window = entry_candles[: i + 1]
        signal = strategy.evaluate(window, confirm_window, now=as_of, context=context)

        if signal.direction != SignalDirection.NO_TRADE:
            fill_candle = entry_candles[i + 1]
            fill_price = entry_fill_price(signal, fill_candle, config)
            gapped = gapped_through_stop(signal.direction, fill_price, signal.stop_loss)
            opened.append(
                OpenedTrade(
                    signal=signal,
                    fill_timestamp=fill_candle.timestamp,
                    fill_price=fill_price,
                    fill_candle_index=i + 1,
                    gapped_through_stop=gapped,
                )
            )
            context = EvaluationContext(
                last_signal_time=signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )

    return opened


def simulate_trade_management(
    opened: OpenedTrade,
    entry_candles: list[Candle],
    *,
    preset: TradeManagementPreset,
    shortfall_mode: TpShortfallHandling,
    breakeven_rule: BreakevenRule,
    transaction_cost: float,
) -> BacktestTrade:
    """Replay candles from the fill candle onward against the trade's stop
    and targets, simulating this preset's partial closes and the
    configured breakeven rule. Same-candle stop+target collisions are
    resolved conservatively: the stop is assumed to trigger first.
    """
    signal = opened.signal
    is_buy = signal.direction == SignalDirection.BUY
    initial_stop = signal.stop_loss
    fill_price = opened.fill_price

    if opened.gapped_through_stop:
        risk = max(abs(fill_price - initial_stop), 1e-9)
        return BacktestTrade(
            signal_id=signal.signal_id,
            strategy_mode=signal.strategy_mode,
            strategy_version=signal.strategy_version,
            trade_management_preset=preset,
            direction=signal.direction,
            signal_timestamp=signal.signal_timestamp,
            fill_timestamp=opened.fill_timestamp,
            fill_price=fill_price,
            initial_stop_loss=initial_stop,
            risk=risk,
            exit_timestamp=opened.fill_timestamp,
            exit_price=fill_price,
            exit_reason="stop",
            realized_r=-1.0 - transaction_cost / risk,
            is_full_stop=True,
            breakeven_triggered=False,
        )

    risk = abs(fill_price - initial_stop)
    targets = signal.targets
    allocations = resolve_allocations(preset, len(targets), shortfall_mode)

    current_stop = initial_stop
    remaining_fraction = 1.0
    target_fills: list[TargetFill] = []
    stop_adjustments: list[StopAdjustment] = []
    targets_hit: set[str] = set()
    breakeven_triggered = False

    exit_timestamp: datetime | None = None
    exit_price: float | None = None
    exit_reason = ""
    final_contribution = 0.0

    for c in entry_candles[opened.fill_candle_index :]:
        stop_touched = c.low <= current_stop if is_buy else c.high >= current_stop
        if stop_touched:
            exit_price = current_stop
            exit_timestamp = c.timestamp
            exit_reason = "breakeven_stop" if current_stop != initial_stop else "stop"
            r_at_exit = (
                (exit_price - fill_price) / risk if is_buy else (fill_price - exit_price) / risk
            )
            final_contribution = remaining_fraction * r_at_exit
            break

        for idx, target in enumerate(targets):
            if target.label in targets_hit:
                continue
            touched = c.high >= target.price if is_buy else c.low <= target.price
            if not touched:
                continue
            allocation = allocations[idx]
            r_multiple = (
                (target.price - fill_price) / risk if is_buy else (fill_price - target.price) / risk
            )
            contribution = allocation * r_multiple
            target_fills.append(
                TargetFill(
                    label=target.label,
                    price=target.price,
                    timestamp=c.timestamp,
                    allocation=allocation,
                    r_multiple=r_multiple,
                    r_contribution=contribution,
                )
            )
            targets_hit.add(target.label)
            remaining_fraction -= allocation

            if (
                breakeven_rule.trigger == BreakevenTrigger.AFTER_TP1_CONFIRMED
                and target.label == "TP1"
                and current_stop == initial_stop
            ):
                current_stop = fill_price
                breakeven_triggered = True
                stop_adjustments.append(
                    StopAdjustment(
                        timestamp=c.timestamp, new_stop=current_stop, reason="after_tp1_confirmed"
                    )
                )

        if (
            breakeven_rule.trigger == BreakevenTrigger.AFTER_R_MULTIPLE
            and current_stop == initial_stop
        ):
            favorable = c.high if is_buy else c.low
            r_reached = (
                (favorable - fill_price) / risk if is_buy else (fill_price - favorable) / risk
            )
            if r_reached >= (breakeven_rule.after_r_multiple or 0):
                current_stop = fill_price
                breakeven_triggered = True
                stop_adjustments.append(
                    StopAdjustment(
                        timestamp=c.timestamp,
                        new_stop=current_stop,
                        reason=f"after_{breakeven_rule.after_r_multiple}r",
                    )
                )

        if remaining_fraction <= 1e-9:
            exit_price = target_fills[-1].price
            exit_timestamp = c.timestamp
            exit_reason = "all_targets_hit"
            final_contribution = 0.0
            break
    else:
        last_candle = entry_candles[-1]
        exit_price = last_candle.close
        exit_timestamp = last_candle.timestamp
        exit_reason = "data_end_mark_to_market"
        r_at_exit = (exit_price - fill_price) / risk if is_buy else (fill_price - exit_price) / risk
        final_contribution = remaining_fraction * r_at_exit

    realized_r = sum(tf.r_contribution for tf in target_fills) + final_contribution
    realized_r -= transaction_cost / risk

    return BacktestTrade(
        signal_id=signal.signal_id,
        strategy_mode=signal.strategy_mode,
        strategy_version=signal.strategy_version,
        trade_management_preset=preset,
        direction=signal.direction,
        signal_timestamp=signal.signal_timestamp,
        fill_timestamp=opened.fill_timestamp,
        fill_price=fill_price,
        initial_stop_loss=initial_stop,
        risk=risk,
        target_fills=target_fills,
        stop_adjustments=stop_adjustments,
        exit_timestamp=exit_timestamp,
        exit_price=exit_price,
        exit_reason=exit_reason,
        realized_r=realized_r,
        is_full_stop=not target_fills and exit_reason in ("stop", "breakeven_stop"),
        breakeven_triggered=breakeven_triggered,
    )
