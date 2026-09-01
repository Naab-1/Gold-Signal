from datetime import UTC, datetime

from goldsignal.analysis.frequency import analyze_frequency
from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.strategy.scalp import ScalpStrategy

START = datetime(2026, 1, 1, tzinfo=UTC)

_LOOSE_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "ESTIMATED_SPREAD": "0.3",
    "ESTIMATED_SLIPPAGE": "0.2",
    "MIN_NET_REWARD_R": "0.3",
    "CHOP_FILTER_ATR_MULTIPLE": "0.05",
    "TREND_STRENGTH_ATR_MULTIPLE": "0.1",
    "RSI_BUY_THRESHOLD": "40",
    "RSI_SELL_THRESHOLD": "60",
    "RSI_OVERBOUGHT": "95",
    "RSI_OVERSOLD": "5",
    "RETEST_TOLERANCE_ATR_FRACTION": "1.0",
    "RETEST_CONFIRM_WINDOW": "10",
    "STRUCTURE_LOOKBACK": "8",
}


def _loose_env():
    return {f"GOLDSIGNAL_SCALP_{k}": v for k, v in _LOOSE_OVERRIDES.items()}


def _build(seed=3, candle_count=600):
    config = load_scalp_config(_loose_env())
    strategy = ScalpStrategy(config, "XAUUSD")
    provider = MockDataProvider(seed=seed, base_price=2400.0, volatility=6.0)
    end = START + config.entry_timeframe.duration * candle_count
    entry = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)
    return strategy, entry, confirm


def test_stage_counts_sum_to_total_candles():
    strategy, entry, confirm = _build()
    report = analyze_frequency(strategy, entry, confirm, instrument="XAUUSD")
    assert sum(report.stage_counts.values()) == report.total_candles


def test_funnel_is_monotonically_non_increasing_and_cost_qualified_equals_final_signals():
    strategy, entry, confirm = _build()
    report = analyze_frequency(strategy, entry, confirm, instrument="XAUUSD")
    f = report.funnel
    assert f["completed_candles"] >= f["trend_qualified"] >= f["setup_qualified"]
    assert f["setup_qualified"] >= f["entry_confirmed"] >= f["cost_qualified"]
    assert f["cost_qualified"] == f["final_signals"]


def test_at_least_one_signal_and_near_miss_found_with_loosened_thresholds():
    strategy, entry, confirm = _build()
    report = analyze_frequency(strategy, entry, confirm, instrument="XAUUSD")
    assert report.funnel["final_signals"] > 0
    assert sum(report.rejection_counts_single.values()) > 0


def test_rejection_combination_keys_reflect_failed_conditions():
    strategy, entry, confirm = _build()
    report = analyze_frequency(strategy, entry, confirm, instrument="XAUUSD")
    for combo_key in report.rejection_combinations:
        names = combo_key.split(",")
        assert all(
            n
            in (
                "not_choppy",
                "rsi_confirmation",
                "breakout_retest_confirmed",
                "sufficient_reward_after_costs",
            )
            for n in names
        )


def test_dev_and_out_of_sample_counts_sum_to_final_signals():
    strategy, entry, confirm = _build()
    report = analyze_frequency(strategy, entry, confirm, instrument="XAUUSD", split_ratio=0.7)
    assert (
        report.development_signal_count + report.out_of_sample_signal_count
        == report.funnel["final_signals"]
    )


def test_signals_without_cost_filter_is_at_least_final_signal_count():
    # Zeroing costs can only ever accept a superset of what real costs allow.
    strategy, entry, confirm = _build()
    report = analyze_frequency(strategy, entry, confirm, instrument="XAUUSD")
    assert report.signals_without_cost_filter >= report.funnel["final_signals"]


def test_no_candles_returns_zeroed_report():
    strategy, entry, confirm = _build()
    report = analyze_frequency(strategy, entry[:1], confirm, instrument="XAUUSD")
    assert report.total_candles == 0
    assert report.funnel["final_signals"] == 0
