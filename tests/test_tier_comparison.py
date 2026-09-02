"""Tests for the independent A+/two-candle/one-candle historical
comparison harness. Uses the same loosened-threshold mock-data scan
pattern as test_classification.py so all three variants produce trades
within a short synthetic series.
"""

from __future__ import annotations

from datetime import UTC, datetime

from goldsignal.analysis.tier_comparison import (
    ALL_VARIANTS,
    VARIANT_A_PLUS,
    VARIANT_ONE_CANDLE,
    VARIANT_TWO_CANDLE,
    run_tier_comparison,
)
from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.signal import StrategyMode
from goldsignal.strategy.scalp import ScalpStrategy

START = datetime(2026, 1, 1, tzinfo=UTC)

_LOOSE_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "ESTIMATED_SPREAD": "0.02",
    "ESTIMATED_SLIPPAGE": "0.01",
    "MIN_NET_REWARD_R": "0.1",
    "A_TIER_MIN_NET_REWARD_R": "0.05",
    "CHOP_FILTER_ATR_MULTIPLE": "0.05",
    "TREND_STRENGTH_ATR_MULTIPLE": "0.1",
    "RSI_BUY_THRESHOLD": "40",
    "RSI_SELL_THRESHOLD": "60",
    "RSI_OVERBOUGHT": "95",
    "RSI_OVERSOLD": "5",
    "RETEST_TOLERANCE_ATR_FRACTION": "1.0",
    "RETEST_CONFIRM_WINDOW": "10",
    "STRUCTURE_LOOKBACK": "20",
    "CONTINUATION_BREAKOUT_MIN_ATR_MULTIPLE": "0.02",
    "CONTINUATION_MIN_BODY_RATIO": "0.3",
    "CONTINUATION_CLOSE_POSITION_RATIO": "0.4",
    "CONTINUATION_MAX_RANGE_ATR_MULTIPLE": "5.0",
    "CONTINUATION_CONFIRMATION_TOLERANCE_ATR_FRACTION": "1.0",
}


def _config():
    return load_scalp_config({f"GOLDSIGNAL_SCALP_{k}": v for k, v in _LOOSE_OVERRIDES.items()})


def _candles(config):
    provider = MockDataProvider(seed=4, base_price=2400.0, volatility=6.0)
    end = START + config.entry_timeframe.duration * 3000
    entry = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)
    return entry, confirm


def test_all_three_variants_report_separately_and_produce_trades():
    config = _config()
    entry, confirm = _candles(config)
    strategy = ScalpStrategy(config, "XAUUSD")

    report = run_tier_comparison(
        strategy, StrategyMode.SCALP, "scalp_test_v1", config, "XAUUSD", entry, confirm
    )

    assert set(report.grade_counts.keys()) == set(ALL_VARIANTS)
    # Each variant must have produced at least one actionable trade in this
    # loosened scan, and dev+oos trade counts must equal the variant's own
    # actionable-grade tally (A_PLUS for the baseline, A for the other two).
    for variant in ALL_VARIANTS:
        actionable_grade = "A_PLUS" if variant == VARIANT_A_PLUS else "A"
        actionable_count = report.grade_counts[variant].get(actionable_grade, 0)
        assert actionable_count > 0, f"{variant} produced no actionable signals in the scan"
        split_total = sum(s.summary.total_trades for s in report.splits if s.variant == variant)
        assert split_total == actionable_count


def test_variant_summaries_are_never_blended():
    """Splits are physically separate BacktestSummary objects per variant
    — there is no code path that could average an A+ and an A statistic
    together.
    """
    config = _config()
    entry, confirm = _candles(config)
    strategy = ScalpStrategy(config, "XAUUSD")

    report = run_tier_comparison(
        strategy, StrategyMode.SCALP, "scalp_test_v1", config, "XAUUSD", entry, confirm
    )

    # Exactly one development + one out_of_sample summary per variant, and
    # each summary object belongs to exactly one variant.
    by_variant = {v: [s for s in report.splits if s.variant == v] for v in ALL_VARIANTS}
    for splits in by_variant.values():
        labels = {s.split_label for s in splits}
        assert labels == {"development", "out_of_sample"}


def test_worse_case_costs_never_increase_trade_count():
    """Stricter spread/slippage/transaction-cost assumptions can only make
    the net-reward-r gate harder to clear, never easier — so the worse-case
    walk's trade count per variant must be <= the baseline walk's.
    """
    config = _config()
    entry, confirm = _candles(config)
    strategy = ScalpStrategy(config, "XAUUSD")

    report = run_tier_comparison(
        strategy, StrategyMode.SCALP, "scalp_test_v1", config, "XAUUSD", entry, confirm
    )

    baseline_totals = {
        variant: sum(s.summary.total_trades for s in report.splits if s.variant == variant)
        for variant in ALL_VARIANTS
    }
    worse_case_totals = {
        variant: sum(
            s.summary.total_trades for s in report.worse_case_splits if s.variant == variant
        )
        for variant in ALL_VARIANTS
    }
    for variant in ALL_VARIANTS:
        assert worse_case_totals[variant] <= baseline_totals[variant]


def test_two_candle_and_one_candle_signals_are_tagged_distinctly():
    config = _config()
    entry, confirm = _candles(config)
    strategy = ScalpStrategy(config, "XAUUSD")

    from goldsignal.analysis.tier_comparison import _walk
    from goldsignal.strategy.trade_management import TradeManagementPreset

    versions_by_variant: dict[str, set[str]] = {}

    for variant in (VARIANT_TWO_CANDLE, VARIANT_ONE_CANDLE, VARIANT_A_PLUS):
        result = _walk(
            variant,
            strategy=strategy,
            mode=StrategyMode.SCALP,
            version="scalp_test_v1",
            config=config,
            instrument="XAUUSD",
            entry_candles=entry,
            confirmation_candles=confirm,
            preset=TradeManagementPreset.BALANCED,
            transaction_cost=config.estimated_transaction_cost,
        )
        versions_by_variant[variant] = {t.strategy_version for t in result.trades}

    # A+ reuses the real Strategy object, so its trades carry the actual
    # production strategy.version, not the "scalp_test_v1" label passed to
    # the two comparison-only variants below.
    assert versions_by_variant[VARIANT_A_PLUS] == {strategy.version}
    assert versions_by_variant[VARIANT_TWO_CANDLE] == {"scalp_test_v1+two_candle_continuation"}
    assert versions_by_variant[VARIANT_ONE_CANDLE] == {"scalp_test_v1+one_candle_breakout"}
