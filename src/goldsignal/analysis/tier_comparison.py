"""Independent A+ / two-candle continuation (A) / one-candle breakout
comparison over real history.

Each variant is walked SEPARATELY, trying only its own rule at every
candle — none of the three ever falls back to another, so their trade
sets (and therefore their performance statistics) can never mix. This is
deliberate: the user's instruction is that A+ and A statistics must never
be combined, and the one-candle variant exists only to be measured
against both, not to be blended into either.

All three variants use the *same* bounded recent-history window at every
step (`_PRODUCTION_LOOKBACK_CANDLES`, matching `live/run_once.py`'s own
`_LOOKBACK_CANDLES=300`) rather than replaying the entire preceding
series from scratch each step. EMA50/RSI14/ATR14/structure-lookback all
have finite effective memory well under 300 candles, so this doesn't
change what any rule decides — it's what a live deployment already sees,
and it's what makes walking a multi-year 5-minute series tractable
(unbounded per-step recomputation is O(n^2) and impractical past a few
months of 5-minute data).

Reuses the existing, unmodified fill/trade-management/metrics machinery
(`backtest/engine.py`, `backtest/metrics.py`, `backtest/split.py`) —
only the walking loop and rule dispatch are new.
"""

from __future__ import annotations

import bisect
import dataclasses
from collections import Counter
from datetime import date, datetime

from goldsignal.backtest.engine import (
    entry_fill_price,
    gapped_through_stop,
    simulate_trade_management,
)
from goldsignal.backtest.metrics import compute_summary
from goldsignal.backtest.models import BacktestSummary, BacktestTrade, OpenedTrade
from goldsignal.backtest.split import split_cutoff_timestamp, split_trades
from goldsignal.config import ModeConfig
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.notifications.sessions import session_label
from goldsignal.strategy.base import EvaluationContext, Strategy
from goldsignal.strategy.classification import (
    ClassificationResult,
    PendingContinuation,
    SignalGrade,
    evaluate_a_tier_continuation,
    evaluate_one_candle_breakout,
)
from goldsignal.strategy.trade_management import BreakevenRule, TradeManagementPreset

_PRODUCTION_LOOKBACK_CANDLES = 300

VARIANT_A_PLUS = "a_plus_baseline"
VARIANT_TWO_CANDLE = "two_candle_continuation"
VARIANT_ONE_CANDLE = "one_candle_breakout"
ALL_VARIANTS = (VARIANT_A_PLUS, VARIANT_TWO_CANDLE, VARIANT_ONE_CANDLE)


@dataclasses.dataclass
class TierWalkResult:
    variant: str
    trades: list[BacktestTrade]
    grade_counts: dict[str, int]
    total_days: int
    zero_signal_days: int
    signals_by_session: dict[str, int]


def _walk(
    variant: str,
    *,
    strategy: Strategy,
    mode: StrategyMode,
    version: str,
    config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    preset: TradeManagementPreset,
    transaction_cost: float,
) -> TierWalkResult:
    entry_duration = config.entry_timeframe.duration
    confirm_duration = config.confirmation_timeframe.duration
    confirm_close_times = [c.timestamp + confirm_duration for c in confirmation_candles]
    breakeven_rule = BreakevenRule(
        trigger=config.breakeven_trigger, after_r_multiple=config.breakeven_after_r_multiple
    )

    def step(
        window: list[Candle],
        confirm_window: list[Candle],
        now: datetime,
        context: EvaluationContext,
        pending: PendingContinuation | None,
    ) -> ClassificationResult:
        if variant == VARIANT_A_PLUS:
            signal = strategy.evaluate(window, confirm_window, now=now, context=context)
            if signal.direction == SignalDirection.NO_TRADE:
                return ClassificationResult(grade=SignalGrade.NO_TRADE, signal=None, pending=None)
            return ClassificationResult(grade=SignalGrade.A_PLUS, signal=signal, pending=None)
        if variant == VARIANT_TWO_CANDLE:
            return evaluate_a_tier_continuation(
                mode=mode,
                version=version,
                config=config,
                instrument=instrument,
                entry_candles=window,
                confirmation_candles=confirm_window,
                now=now,
                context=context,
                pending=pending,
            )
        if variant == VARIANT_ONE_CANDLE:
            return evaluate_one_candle_breakout(
                mode=mode,
                version=version,
                config=config,
                instrument=instrument,
                entry_candles=window,
                confirmation_candles=confirm_window,
                now=now,
                context=context,
            )
        raise ValueError(f"unknown variant: {variant}")

    context = EvaluationContext()
    session_date: date | None = None
    pending: PendingContinuation | None = None
    grade_counts: Counter[str] = Counter()
    signals_by_session: Counter[str] = Counter()
    trading_days: set[date] = set()
    actionable_days: set[date] = set()
    trades: list[BacktestTrade] = []

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

        result = step(window, confirm_window, as_of, context, pending)
        pending = result.pending
        grade_counts[result.grade.value] += 1

        if result.signal is not None:
            fill_candle = entry_candles[i + 1]
            fill_price = entry_fill_price(result.signal, fill_candle, config)
            gapped = gapped_through_stop(
                result.signal.direction, fill_price, result.signal.stop_loss
            )
            opened = OpenedTrade(
                signal=result.signal,
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
                transaction_cost=transaction_cost,
            )
            trades.append(trade)
            actionable_days.add(current_date)
            signals_by_session[session_label(result.signal.signal_timestamp)] += 1
            context = EvaluationContext(
                last_signal_time=result.signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )

    return TierWalkResult(
        variant=variant,
        trades=trades,
        grade_counts=dict(grade_counts),
        total_days=len(trading_days),
        zero_signal_days=len(trading_days - actionable_days),
        signals_by_session=dict(signals_by_session),
    )


@dataclasses.dataclass
class VariantSplitSummary:
    variant: str
    split_label: str  # "development" | "out_of_sample"
    summary: BacktestSummary
    signals_per_day: float
    signals_by_session: dict[str, int]


@dataclasses.dataclass
class TierComparisonReport:
    mode: str
    span_days: float
    total_trading_days: int
    zero_signal_days: dict[str, int]  # variant -> count, over the full range
    grade_counts: dict[str, dict[str, int]]  # variant -> grade -> count, over the full range
    splits: list[VariantSplitSummary]  # never mixes variants within one summary
    worse_case_splits: list[VariantSplitSummary]  # same, under stressed costs


def run_tier_comparison(
    strategy: Strategy,
    mode: StrategyMode,
    version: str,
    config: ModeConfig,
    instrument: str,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    *,
    preset: TradeManagementPreset = TradeManagementPreset.BALANCED,
    split_ratio: float = 0.7,
    worse_case_cost_multiplier: float = 3.0,
    variants: tuple[str, ...] = ALL_VARIANTS,
) -> TierComparisonReport:
    if len(entry_candles) > 1:
        span_days = (
            entry_candles[-1].timestamp - entry_candles[0].timestamp
        ).total_seconds() / 86400
        span_days = max(span_days, 1e-9)
    else:
        span_days = 1.0

    cutoff = split_cutoff_timestamp(entry_candles, split_ratio) if len(entry_candles) > 1 else None

    zero_signal_days: dict[str, int] = {}
    grade_counts: dict[str, dict[str, int]] = {}
    splits: list[VariantSplitSummary] = []
    worse_case_splits: list[VariantSplitSummary] = []
    total_trading_days = 0

    stressed_cost = config.estimated_transaction_cost * worse_case_cost_multiplier
    stressed_spread = config.estimated_spread * worse_case_cost_multiplier
    stressed_slippage = config.estimated_slippage * worse_case_cost_multiplier
    stressed_config = dataclasses.replace(
        config,
        estimated_spread=stressed_spread,
        estimated_slippage=stressed_slippage,
        estimated_transaction_cost=stressed_cost,
    )

    for variant in variants:
        result = _walk(
            variant,
            strategy=strategy,
            mode=mode,
            version=version,
            config=config,
            instrument=instrument,
            entry_candles=entry_candles,
            confirmation_candles=confirmation_candles,
            preset=preset,
            transaction_cost=config.estimated_transaction_cost,
        )
        total_trading_days = max(total_trading_days, result.total_days)
        zero_signal_days[variant] = result.zero_signal_days
        grade_counts[variant] = result.grade_counts

        if cutoff is not None:
            dev_trades, oos_trades = split_trades(result.trades, cutoff)
        else:
            dev_trades, oos_trades = result.trades, []

        for label, trades in (("development", dev_trades), ("out_of_sample", oos_trades)):
            days = max(
                result.total_days * (split_ratio if label == "development" else 1 - split_ratio),
                1e-9,
            )
            summary = compute_summary(trades, strategy_mode=mode, preset=preset, split_label=label)
            by_session: Counter[str] = Counter()
            for t in trades:
                by_session[session_label(t.signal_timestamp)] += 1
            splits.append(
                VariantSplitSummary(
                    variant=variant,
                    split_label=label,
                    summary=summary,
                    signals_per_day=len(trades) / days,
                    signals_by_session=dict(by_session),
                )
            )

        # Worse-case cost stress test: re-walk the same history with
        # spread/slippage/transaction-cost multiplied up. This can also
        # change which candles pass the reward gate (stricter costs make
        # the min-R:R filter harder to clear) as well as realized R on
        # trades that still fire — both are real, intended effects of
        # worse execution conditions, not an artifact.
        stressed_result = _walk(
            variant,
            strategy=strategy,
            mode=mode,
            version=version,
            config=stressed_config,
            instrument=instrument,
            entry_candles=entry_candles,
            confirmation_candles=confirmation_candles,
            preset=preset,
            transaction_cost=stressed_cost,
        )
        if cutoff is not None:
            stressed_dev, stressed_oos = split_trades(stressed_result.trades, cutoff)
        else:
            stressed_dev, stressed_oos = stressed_result.trades, []
        for label, trades in (("development", stressed_dev), ("out_of_sample", stressed_oos)):
            days = max(
                stressed_result.total_days
                * (split_ratio if label == "development" else 1 - split_ratio),
                1e-9,
            )
            summary = compute_summary(trades, strategy_mode=mode, preset=preset, split_label=label)
            worse_case_splits.append(
                VariantSplitSummary(
                    variant=variant,
                    split_label=label,
                    summary=summary,
                    signals_per_day=len(trades) / days,
                    signals_by_session={},
                )
            )

    return TierComparisonReport(
        mode=mode.value,
        span_days=span_days,
        total_trading_days=total_trading_days,
        zero_signal_days=zero_signal_days,
        grade_counts=grade_counts,
        splits=splits,
        worse_case_splits=worse_case_splits,
    )
