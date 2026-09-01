from datetime import UTC, datetime

from goldsignal.analysis.variants import build_variants, run_comparison
from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.strategy.scalp import ScalpStrategy

START = datetime(2026, 1, 1, tzinfo=UTC)


def test_build_variants_current_is_unchanged_base():
    base = load_scalp_config({})
    variants = build_variants(base)
    assert variants["current"] == base


def test_relaxed_variants_differ_only_in_intended_fields():
    base = load_scalp_config({})
    variants = build_variants(base)

    assert variants["relaxed_chop_filter"].chop_filter_atr_multiple < base.chop_filter_atr_multiple
    assert variants["relaxed_chop_filter"].rsi_buy_threshold == base.rsi_buy_threshold

    assert variants["relaxed_rsi_band"].rsi_buy_threshold < base.rsi_buy_threshold
    assert variants["relaxed_rsi_band"].rsi_overbought > base.rsi_overbought
    assert variants["relaxed_rsi_band"].chop_filter_atr_multiple == base.chop_filter_atr_multiple

    assert variants["relaxed_retest_window"].retest_confirm_window > base.retest_confirm_window
    assert variants["relaxed_min_reward"].min_net_reward_r < base.min_net_reward_r


def test_relaxed_all_combined_includes_every_individual_relaxation():
    base = load_scalp_config({})
    variants = build_variants(base)
    combined = variants["relaxed_all_combined"]
    assert (
        combined.chop_filter_atr_multiple
        == variants["relaxed_chop_filter"].chop_filter_atr_multiple
    )
    assert combined.rsi_buy_threshold == variants["relaxed_rsi_band"].rsi_buy_threshold
    assert combined.retest_confirm_window == variants["relaxed_retest_window"].retest_confirm_window
    assert combined.min_net_reward_r == variants["relaxed_min_reward"].min_net_reward_r


def test_run_comparison_produces_a_result_per_variant_without_mutating_base():
    base = load_scalp_config({"GOLDSIGNAL_SCALP_COOLDOWN_MINUTES": "0"})
    provider = MockDataProvider(seed=5, base_price=2400.0, volatility=6.0)
    end = START + base.entry_timeframe.duration * 600
    entry = provider.get_candles("XAUUSD", base.entry_timeframe, START, end)
    confirm = provider.get_candles("XAUUSD", base.confirmation_timeframe, START, end)

    results = run_comparison(
        ScalpStrategy, ScalpStrategy(base, "XAUUSD").mode, base, "XAUUSD", entry, confirm
    )

    names = {r.variant_name for r in results}
    assert names == {
        "current",
        "relaxed_chop_filter",
        "relaxed_rsi_band",
        "relaxed_retest_window",
        "relaxed_min_reward",
        "relaxed_all_combined",
    }
    for r in results:
        assert r.total_trades >= 0
        assert r.trades_per_day >= 0
        assert r.summary.total_trades == r.total_trades

    current_result = next(r for r in results if r.variant_name == "current")
    assert current_result.config == base
