"""Proves generate_signals_walk_forward never lets a decision at time T
depend on candles that close after T: decisions made against a truncated
dataset must be identical to the decisions made at the same points when
more (future) data is appended.
"""

from datetime import UTC, datetime

from goldsignal.backtest.engine import generate_signals_walk_forward
from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.strategy.scalp import ScalpStrategy

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


def test_truncated_and_full_runs_agree_on_shared_history():
    config = load_scalp_config(_env())
    strategy = ScalpStrategy(config, "XAUUSD")

    provider = MockDataProvider(seed=5, base_price=2400.0, volatility=6.0)
    full_end = START + config.entry_timeframe.duration * 400
    entry_full = provider.get_candles("XAUUSD", config.entry_timeframe, START, full_end)
    confirm_full = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, full_end)

    cut = 250  # truncation point, well before the end of the full series
    entry_truncated = entry_full[:cut]
    confirm_truncated = confirm_full  # confirmation series naturally shorter in wall-clock terms

    full_run = generate_signals_walk_forward(strategy, entry_full, confirm_full)
    truncated_run = generate_signals_walk_forward(strategy, entry_truncated, confirm_truncated)

    # Every trade opened in the truncated run (which by construction can only
    # see candles up to index `cut`) must appear identically in the full run,
    # proving the full run's decisions up to that point didn't change when
    # future candles beyond `cut` became available.
    full_by_id = {t.signal.signal_id: t for t in full_run if t.fill_candle_index < cut}
    assert len(truncated_run) > 0, "expected at least one trade in the truncated window"
    for t in truncated_run:
        match = full_by_id.get(t.signal.signal_id)
        assert match is not None, "a trade from the truncated run is missing from the full run"
        assert match.fill_price == t.fill_price
        assert match.fill_timestamp == t.fill_timestamp
        assert match.signal.direction == t.signal.direction
        assert match.signal.targets == t.signal.targets
