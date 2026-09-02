"""Real-history frequency/funnel analysis.

Walks candles through `evaluate_with_trace` — the exact same rule
function the live strategy uses — never a second implementation, so this
can't drift from what actually runs. Tallies where candles fall out of
the pipeline, near-misses, session/weekday distribution, and a
before/after-costs comparison.
"""

from __future__ import annotations

import bisect
import dataclasses
from collections import Counter
from datetime import date, datetime

from goldsignal.backtest.split import split_cutoff_timestamp
from goldsignal.models.candle import Candle
from goldsignal.models.signal import SignalDirection
from goldsignal.notifications.sessions import session_label
from goldsignal.strategy._common import evaluate_with_trace
from goldsignal.strategy.base import EvaluationContext, Strategy
from goldsignal.strategy.trace import (
    COOLDOWN_BLOCKED,
    COST_REJECTED,
    ENTRY_NOT_CONFIRMED,
    INDICATORS_UNAVAILABLE,
    INSUFFICIENT_DATA,
    NO_TREND_ALIGNMENT,
    SESSION_LIMIT_BLOCKED,
    SETUP_FAILED,
    SIGNAL_EMITTED,
)

_MAX_NEAR_MISSES_KEPT = 50


@dataclasses.dataclass
class FrequencyReport:
    mode: str
    total_candles: int
    funnel: dict[str, int]
    stage_counts: dict[str, int]
    rejection_counts_single: dict[str, int]
    rejection_combinations: dict[str, int]
    near_misses: list[dict]
    signals_by_session: dict[str, int]
    signals_by_weekday: dict[str, int]
    max_consecutive_no_signal: int
    development_signal_count: int
    out_of_sample_signal_count: int
    signals_without_cost_filter: int


def analyze_frequency(
    strategy: Strategy,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    *,
    instrument: str,
    split_ratio: float = 0.7,
) -> FrequencyReport:
    config = strategy.config
    entry_duration = config.entry_timeframe.duration
    confirm_duration = config.confirmation_timeframe.duration
    confirm_close_times = [c.timestamp + confirm_duration for c in confirmation_candles]

    context = EvaluationContext()
    zero_cost_config = dataclasses.replace(
        config, estimated_spread=0.0, estimated_slippage=0.0, estimated_transaction_cost=0.0
    )
    zero_cost_context = EvaluationContext()
    session_date: date | None = None

    stage_counts: Counter[str] = Counter()
    rejection_counts_single: Counter[str] = Counter()
    rejection_combinations: Counter[str] = Counter()
    near_misses: list[dict] = []
    signals_by_session: Counter[str] = Counter()
    signals_by_weekday: Counter[str] = Counter()
    zero_cost_signal_count = 0
    consecutive_no_signal = 0
    max_consecutive_no_signal = 0
    development_signal_count = 0
    out_of_sample_signal_count = 0

    cutoff: datetime | None = (
        split_cutoff_timestamp(entry_candles, split_ratio) if len(entry_candles) > 1 else None
    )

    min_entry_index = 1
    for i in range(min_entry_index, len(entry_candles) - 1):
        signal_candle = entry_candles[i]
        as_of = signal_candle.timestamp + entry_duration

        # max_signals_per_session is a *daily* cap in production (see
        # live/run_once.py and tier_comparison.py's identical reset) --
        # without resetting signals_emitted_this_session at each new day,
        # it instead becomes a one-time, whole-test-lifetime cap: the
        # first max_signals_per_session real signals across the entire
        # multi-month/year run permanently trip SESSION_LIMIT_BLOCKED for
        # every candle afterward, making the reported frequency collapse
        # to roughly that config value regardless of how much history
        # remains. This under-reported real signal frequency by close to
        # an order of magnitude before being caught.
        current_date = as_of.date()
        if session_date != current_date:
            session_date = current_date
            context = EvaluationContext(last_signal_time=context.last_signal_time)
            zero_cost_context = EvaluationContext(
                last_signal_time=zero_cost_context.last_signal_time
            )

        window = entry_candles[: i + 1]
        confirm_idx = bisect.bisect_right(confirm_close_times, as_of)
        confirm_window = confirmation_candles[:confirm_idx]

        signal, trace = evaluate_with_trace(
            mode=strategy.mode,
            version=strategy.version,
            config=config,
            instrument=instrument,
            entry_candles=window,
            confirmation_candles=confirm_window,
            now=as_of,
            context=context,
        )
        stage_counts[trace.stage] += 1

        if trace.conditions:
            failed = [name for name, ok in trace.conditions.items() if not ok]
            for name in failed:
                rejection_counts_single[name] += 1
            if failed:
                rejection_combinations[",".join(sorted(failed))] += 1
            if len(failed) == 1 and len(near_misses) < _MAX_NEAR_MISSES_KEPT:
                near_misses.append(
                    {
                        "timestamp": as_of.isoformat(),
                        "blocking_condition": failed[0],
                        "candidate_direction": (
                            trace.candidate_direction.value if trace.candidate_direction else None
                        ),
                    }
                )

        if signal.direction != SignalDirection.NO_TRADE:
            consecutive_no_signal = 0
            signals_by_session[session_label(signal.signal_timestamp)] += 1
            signals_by_weekday[signal.signal_timestamp.strftime("%A")] += 1
            context = EvaluationContext(
                last_signal_time=signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )
            if cutoff is not None and signal.signal_timestamp < cutoff:
                development_signal_count += 1
            elif cutoff is not None:
                out_of_sample_signal_count += 1
        else:
            consecutive_no_signal += 1
            max_consecutive_no_signal = max(max_consecutive_no_signal, consecutive_no_signal)

        zc_signal, _zc_trace = evaluate_with_trace(
            mode=strategy.mode,
            version=strategy.version,
            config=zero_cost_config,
            instrument=instrument,
            entry_candles=window,
            confirmation_candles=confirm_window,
            now=as_of,
            context=zero_cost_context,
        )
        if zc_signal.direction != SignalDirection.NO_TRADE:
            zero_cost_signal_count += 1
            zero_cost_context = EvaluationContext(
                last_signal_time=zc_signal.signal_timestamp,
                signals_emitted_this_session=zero_cost_context.signals_emitted_this_session + 1,
            )

    total_candles = max(0, len(entry_candles) - min_entry_index - 1)
    trend_qualified = (
        total_candles
        - stage_counts[INSUFFICIENT_DATA]
        - stage_counts[COOLDOWN_BLOCKED]
        - stage_counts[SESSION_LIMIT_BLOCKED]
        - stage_counts[INDICATORS_UNAVAILABLE]
        - stage_counts[NO_TREND_ALIGNMENT]
    )
    setup_qualified = trend_qualified - stage_counts[SETUP_FAILED]
    entry_confirmed = setup_qualified - stage_counts[ENTRY_NOT_CONFIRMED]
    cost_qualified = entry_confirmed - stage_counts[COST_REJECTED]
    final_signals = stage_counts[SIGNAL_EMITTED]

    funnel = {
        "completed_candles": total_candles,
        "trend_qualified": trend_qualified,
        "setup_qualified": setup_qualified,
        "entry_confirmed": entry_confirmed,
        "cost_qualified": cost_qualified,
        "final_signals": final_signals,
    }

    return FrequencyReport(
        mode=strategy.mode.value,
        total_candles=total_candles,
        funnel=funnel,
        stage_counts=dict(stage_counts),
        rejection_counts_single=dict(rejection_counts_single),
        rejection_combinations=dict(rejection_combinations),
        near_misses=near_misses,
        signals_by_session=dict(signals_by_session),
        signals_by_weekday=dict(signals_by_weekday),
        max_consecutive_no_signal=max_consecutive_no_signal,
        development_signal_count=development_signal_count,
        out_of_sample_signal_count=out_of_sample_signal_count,
        signals_without_cost_filter=zero_cost_signal_count,
    )
