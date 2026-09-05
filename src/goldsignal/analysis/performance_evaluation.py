"""Performance evaluation (STRATEGY RESEARCH AND REPLACEMENT program,
Phase 7) -- see docs/phase7_performance_evaluation.md for the full
write-up and a worked cross-family comparison against real history.

Two things Phase 5 and Phase 3 each explicitly deferred to this phase:

1. **Regime correlation.** Phase 5's classifier (`analysis/regime.py`)
   was built "for diagnostic use... not this one's" -- this module is
   the "this one." Every trade a candidate produces is tagged with
   whichever regime the market was in at that trade's signal timestamp
   (using only candles at or before that timestamp -- no lookahead),
   so a candidate's development/validation performance can be broken
   down by regime, not just reported as one blended number.
2. **Cross-family comparison.** Phase 4 built five independent
   candidates one at a time and explicitly never blended their
   statistics. This module runs each candidate's OWN walk (via
   `analysis/candidate_walk.py::walk_candidate`, reused unmodified) and
   reports them side by side on development and validation -- still
   never blended into a combined metric, and never touching
   final-out-of-sample data (this module discards that split
   immediately after computing it, the same guardrail
   `run_candidate_dev_validation` already enforces for the
   optimization framework).

Session breakdowns reuse `notifications/sessions.py::session_label`
(the same grouping key `analysis/tier_comparison.py` already uses for
its own per-session counts).
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import dataclass

from goldsignal.analysis.candidate_walk import walk_candidate
from goldsignal.analysis.regime import MarketRegime, RegimeClassifierConfig, classify_regime_series
from goldsignal.backtest.metrics import compute_summary
from goldsignal.backtest.models import BacktestSummary, BacktestTrade
from goldsignal.backtest.split import split_cutoff_timestamps, split_trades_three_way
from goldsignal.models.candle import Candle
from goldsignal.models.signal import StrategyMode
from goldsignal.notifications.sessions import session_label
from goldsignal.strategy.base import Strategy
from goldsignal.strategy.trade_management import TradeManagementPreset

_UNKNOWN_REGIME = "UNKNOWN"


def regime_at_or_before(
    timestamp,
    regime_candles: list[Candle],
    regime_series: list[MarketRegime | None],
) -> MarketRegime | None:
    """The classified regime of the most recent `regime_candles` entry at
    or before `timestamp` -- a lookahead-safe join between a trade's
    signal timestamp and a separately-classified regime series (which
    may be on a different, typically higher, timeframe than the trade's
    own entry candles).
    """
    timestamps = [c.timestamp for c in regime_candles]
    idx = bisect.bisect_right(timestamps, timestamp) - 1
    if idx < 0:
        return None
    return regime_series[idx]


def tag_trades_with_regime(
    trades: list[BacktestTrade],
    regime_candles: list[Candle],
    regime_series: list[MarketRegime | None],
) -> dict[str, list[BacktestTrade]]:
    groups: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in trades:
        regime = regime_at_or_before(trade.signal_timestamp, regime_candles, regime_series)
        key = regime.value if regime is not None else _UNKNOWN_REGIME
        groups[key].append(trade)
    return dict(groups)


def group_trades_by_session(trades: list[BacktestTrade]) -> dict[str, list[BacktestTrade]]:
    groups: dict[str, list[BacktestTrade]] = defaultdict(list)
    for trade in trades:
        groups[session_label(trade.signal_timestamp)].append(trade)
    return dict(groups)


def summarize_groups(
    groups: dict[str, list[BacktestTrade]],
    *,
    strategy_mode: StrategyMode,
    preset: TradeManagementPreset,
    split_label: str,
) -> dict[str, BacktestSummary]:
    return {
        key: compute_summary(
            group_trades, strategy_mode=strategy_mode, preset=preset, split_label=split_label
        )
        for key, group_trades in groups.items()
    }


@dataclass(frozen=True)
class CandidateEvaluation:
    family: str
    instrument: str
    mode: StrategyMode
    development: BacktestSummary
    validation: BacktestSummary
    development_by_regime: dict[str, BacktestSummary]
    validation_by_regime: dict[str, BacktestSummary]
    development_by_session: dict[str, BacktestSummary]
    validation_by_session: dict[str, BacktestSummary]


def evaluate_candidate_performance(
    *,
    family: str,
    instrument: str,
    strategy: Strategy,
    mode: StrategyMode,
    entry_candles: list[Candle],
    confirmation_candles: list[Candle],
    regime_candles: list[Candle],
    regime_config: RegimeClassifierConfig,
    preset: TradeManagementPreset = TradeManagementPreset.BALANCED,
    dev_ratio: float = 0.7,
    validation_ratio: float = 0.15,
) -> CandidateEvaluation:
    """Walks `strategy` once over its own entry/confirmation candles,
    splits the resulting trades development/validation/final-out-of-
    -sample (the final-oos slice is computed then immediately discarded
    -- never inspected or returned, the same guardrail
    `run_candidate_dev_validation` already enforces), and reports
    overall plus regime- and session-broken-down summaries for
    development and validation only.

    `regime_candles`/`regime_config` classify the market independently
    of `strategy`'s own entry timeframe -- typically a shared, higher
    timeframe reused across every candidate being evaluated, so regime
    tags are comparable across families rather than each reading its
    own entry timeframe's noise differently.
    """
    result = walk_candidate(strategy, entry_candles, confirmation_candles, preset=preset)
    cutoff1, cutoff2 = split_cutoff_timestamps(
        entry_candles, dev_ratio=dev_ratio, validation_ratio=validation_ratio
    )
    development, validation, _final_oos = split_trades_three_way(result.trades, cutoff1, cutoff2)

    regime_series = classify_regime_series(regime_candles, regime_config)

    return CandidateEvaluation(
        family=family,
        instrument=instrument,
        mode=mode,
        development=compute_summary(
            development, strategy_mode=mode, preset=preset, split_label="development"
        ),
        validation=compute_summary(
            validation, strategy_mode=mode, preset=preset, split_label="validation"
        ),
        development_by_regime=summarize_groups(
            tag_trades_with_regime(development, regime_candles, regime_series),
            strategy_mode=mode,
            preset=preset,
            split_label="development",
        ),
        validation_by_regime=summarize_groups(
            tag_trades_with_regime(validation, regime_candles, regime_series),
            strategy_mode=mode,
            preset=preset,
            split_label="validation",
        ),
        development_by_session=summarize_groups(
            group_trades_by_session(development),
            strategy_mode=mode,
            preset=preset,
            split_label="development",
        ),
        validation_by_session=summarize_groups(
            group_trades_by_session(validation),
            strategy_mode=mode,
            preset=preset,
            split_label="validation",
        ),
    )
