"""Proves tier_comparison.py's bounded-window `_walk` never lets a decision
at time T depend on candles that close after T -- the same guarantee
`test_backtest_no_lookahead.py` proves for the older, unbounded
`generate_signals_walk_forward`, but for the newer 300-candle-window walk
that now backs every real-history backtest run this project produces
(tier comparisons, per-instrument Phase 2 backtests).
"""

from datetime import UTC, datetime

from goldsignal.analysis.tier_comparison import VARIANT_A_PLUS, _walk
from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.strategy.scalp import ScalpStrategy
from goldsignal.strategy.trade_management import TradeManagementPreset

START = datetime(2026, 1, 1, tzinfo=UTC)

_LOOSE_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "ESTIMATED_SPREAD": "0.0",
    "ESTIMATED_SLIPPAGE": "0.0",
    "MIN_NET_REWARD_R": "0.1",
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


def _env():
    return {f"GOLDSIGNAL_SCALP_{k}": v for k, v in _LOOSE_OVERRIDES.items()}


def test_truncated_and_full_walks_agree_on_shared_history():
    config = load_scalp_config(_env())
    strategy = ScalpStrategy(config, "XAUUSD")

    provider = MockDataProvider(seed=5, base_price=2400.0, volatility=6.0)
    full_end = START + config.entry_timeframe.duration * 400
    entry_full = provider.get_candles("XAUUSD", config.entry_timeframe, START, full_end)
    confirm_full = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, full_end)

    cut = 250
    entry_truncated = entry_full[:cut]

    def run(entry_candles):
        return _walk(
            VARIANT_A_PLUS,
            strategy=strategy,
            mode=strategy.mode,
            version=strategy.version,
            config=config,
            instrument="XAUUSD",
            entry_candles=entry_candles,
            confirmation_candles=confirm_full,
            preset=TradeManagementPreset.BALANCED,
            transaction_cost=config.estimated_transaction_cost,
        )

    full_result = run(entry_full)
    truncated_result = run(entry_truncated)

    assert len(truncated_result.trades) > 0, "expected at least one trade in the truncated window"

    full_by_id = {t.signal_id: t for t in full_result.trades}
    for t in truncated_result.trades:
        match = full_by_id.get(t.signal_id)
        assert match is not None, "a truncated-run trade is missing from the full run"
        assert match.fill_price == t.fill_price
        assert match.fill_timestamp == t.fill_timestamp
        assert match.direction == t.direction
        assert match.initial_stop_loss == t.initial_stop_loss
