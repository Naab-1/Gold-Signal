"""Generic bounded walk-forward evaluator for ONE `Strategy`-protocol
candidate (STRATEGY RESEARCH AND REPLACEMENT program, Phase 4+).

Reuses `analysis/tier_comparison.py`'s own bounded-window walk pattern
(the last 300 candles per step, matching `live/run_once.py`'s own
`_LOOKBACK_CANDLES=300` -- not a full-history replay, which is what makes
walking a multi-year 5-minute series tractable) rather than inventing a
fifth walk implementation. Unlike `tier_comparison.py`, there is only ONE
variant here (whatever `strategy.evaluate(...)` returns) -- no A+/A-tier
dispatch, since every Phase 4 candidate is a fresh, independent strategy,
never blended with another candidate's or the frozen baseline's
statistics.

Wired to Phase 3's `backtest/split.py::split_cutoff_timestamps`/
`split_trades_three_way` for the development/validation/final-out-of-
-sample separation. Callers are responsible for actually gating access to
the final-out-of-sample slice through
`backtest/final_oos_ledger.py::assert_not_yet_evaluated` before ever
reporting a final-oos number -- this module does not enforce that itself,
since it doesn't know a strategy_version's evaluation history.
"""

from __future__ import annotations

import bisect
from collections import Counter
from datetime import date

from goldsignal.backtest.engine import (
    entry_fill_price,
    gapped_through_stop,
    simulate_trade_management,
)
from goldsignal.backtest.metrics import compute_summary
from goldsignal.backtest.models import BacktestSummary, BacktestTrade, OpenedTrade
from goldsignal.backtest.split import split_cutoff_timestamps, split_trades_three_way
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.base import EvaluationContext, Strategy
from goldsignal.strategy.trade_management import BreakevenRule, TradeManagementPreset

_PRODUCTION_LOOKBACK_CANDLES = 300


class CandidateWalkResult:
    """Plain container (not frozen -- built incrementally in `walk_candidate`)."""

    def __init__(self) -> None:
        self.trades: list[BacktestTrade] = []
        self.grade_counts: Counter[str] = Counter()
        self.total_days = 0
        self.zero_signal_days = 0


def walk_candidate(
    strategy: Strategy,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    *,
    preset: TradeManagementPreset = TradeManagementPreset.BALANCED,
    transaction_cost: float | None = None,
) -> CandidateWalkResult:
    """Walk `entry_candles` one closed candle at a time, evaluating
    `strategy` at each step with only the last `_PRODUCTION_LOOKBACK_CANDLES`
    visible -- matching what a live deployment of this candidate would
    actually see. Fills every BUY/SELL at the next candle's open via the
    existing, unmodified `entry_fill_price`/`simulate_trade_management`.
    """
    config = strategy.config
    entry_duration = config.entry_timeframe.duration
    confirm_duration = config.confirmation_timeframe.duration
    confirm_close_times = [c.timestamp + confirm_duration for c in confirmation_candles]
    breakeven_rule = BreakevenRule(
        trigger=config.breakeven_trigger, after_r_multiple=config.breakeven_after_r_multiple
    )
    cost = transaction_cost if transaction_cost is not None else config.estimated_transaction_cost

    result = CandidateWalkResult()
    context = EvaluationContext()
    session_date: date | None = None
    trading_days: set[date] = set()
    actionable_days: set[date] = set()

    for i in range(1, len(entry_candles) - 1):
        signal_candle = entry_candles[i]
        as_of = signal_candle.timestamp + entry_duration
        current_date = as_of.date()
        trading_days.add(current_date)
        if session_date != current_date:
            session_date = current_date
            context = EvaluationContext(last_signal_time=context.last_signal_time)

        window_start = max(0, i + 1 - _PRODUCTION_LOOKBACK_CANDLES)
        window = entry_candles[window_start : i + 1]
        confirm_idx = bisect.bisect_right(confirm_close_times, as_of)
        confirm_window = confirmation_candles[:confirm_idx]

        signal = strategy.evaluate(window, confirm_window, now=as_of, context=context)
        result.grade_counts[signal.direction.value] += 1

        if signal.direction != SignalDirection.NO_TRADE:
            fill_candle = entry_candles[i + 1]
            fill_price = entry_fill_price(signal, fill_candle, config)
            gapped = gapped_through_stop(signal.direction, fill_price, signal.stop_loss)
            opened = OpenedTrade(
                signal=signal,
                fill_timestamp=fill_candle.timestamp,
                fill_price=fill_price,
                fill_candle_index=i + 1,
                gapped_through_stop=gapped,
            )
            trade = simulate_trade_management(
                opened,
                entry_candles,
                preset=preset,
                shortfall_mode=config.tp_shortfall_handling,
                breakeven_rule=breakeven_rule,
                transaction_cost=cost,
                estimated_spread=config.estimated_spread,
                estimated_slippage=config.estimated_slippage,
            )
            result.trades.append(trade)
            actionable_days.add(current_date)
            context = EvaluationContext(
                last_signal_time=signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )

    result.total_days = len(trading_days)
    result.zero_signal_days = len(trading_days - actionable_days)
    return result


class CandidateDevValidationSummary:
    def __init__(
        self,
        *,
        development: BacktestSummary,
        validation: BacktestSummary,
        grade_counts: dict[str, int],
        total_days: int,
        zero_signal_days: int,
    ) -> None:
        self.development = development
        self.validation = validation
        self.grade_counts = grade_counts
        self.total_days = total_days
        self.zero_signal_days = zero_signal_days


def run_candidate_dev_validation(
    strategy: Strategy,
    mode: StrategyMode,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    *,
    preset: TradeManagementPreset = TradeManagementPreset.BALANCED,
    dev_ratio: float = 0.7,
    validation_ratio: float = 0.15,
) -> CandidateDevValidationSummary:
    """Development + validation summaries only -- deliberately does NOT
    return a final-out-of-sample summary. Getting to final-oos requires a
    separate, explicit step through `final_oos_ledger.py`'s guard, per
    Phase 3's rule that it may only ever be evaluated once per
    strategy_version.
    """
    result = walk_candidate(strategy, entry_candles, confirmation_candles, preset=preset)
    cutoff1, cutoff2 = split_cutoff_timestamps(
        entry_candles, dev_ratio=dev_ratio, validation_ratio=validation_ratio
    )
    development, validation, _final_oos = split_trades_three_way(result.trades, cutoff1, cutoff2)
    return CandidateDevValidationSummary(
        development=compute_summary(
            development, strategy_mode=mode, preset=preset, split_label="development"
        ),
        validation=compute_summary(
            validation, strategy_mode=mode, preset=preset, split_label="validation"
        ),
        grade_counts=dict(result.grade_counts),
        total_days=result.total_days,
        zero_signal_days=result.zero_signal_days,
    )
