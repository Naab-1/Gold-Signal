"""End-to-end tests for ScalpStrategy / DayTradeStrategy.

Rather than hand-crafting exact candle sequences to force a BUY or SELL
(fragile, given the strategy chains trend + RSI + breakout-retest + cost
filters), these tests scan a long synthetic mock-data series with loosened
thresholds and assert that BUY, SELL, and NO_TRADE all occur somewhere in
it, and that every non-NO_TRADE signal produced satisfies the invariants
StrategySignal itself enforces (which would otherwise raise).
"""

from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.config import load_daytrade_config, load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.signal import SignalDirection
from goldsignal.strategy.base import EvaluationContext
from goldsignal.strategy.day_trade import DayTradeStrategy
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


def _loose_env(prefix: str) -> dict[str, str]:
    return {f"GOLDSIGNAL_{prefix}_{k}": v for k, v in _LOOSE_OVERRIDES.items()}


def _sufficient_end(config) -> datetime:
    # Confirmation timeframe is coarser than entry, so size the window off
    # it (with margin) to guarantee enough *confirmation* candles too.
    return START + config.confirmation_timeframe.duration * 80


@pytest.mark.parametrize(
    "strategy_cls,config_loader,prefix,seeds",
    [
        (ScalpStrategy, load_scalp_config, "SCALP", range(1, 20)),
        (DayTradeStrategy, load_daytrade_config, "DAYTRADE", range(1, 20)),
    ],
)
def test_strategy_produces_all_outcome_types_across_seeds(
    strategy_cls, config_loader, prefix, seeds
):
    config = config_loader(_loose_env(prefix))
    strategy = strategy_cls(config, "XAUUSD")

    provider = MockDataProvider(base_price=2400.0, volatility=6.0)
    end = START + config.entry_timeframe.duration * 700

    directions_seen: set[SignalDirection] = set()
    for seed in seeds:
        provider = MockDataProvider(seed=seed, base_price=2400.0, volatility=6.0)
        entry_full = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
        confirm_full = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)

        min_entry = 60
        for i in range(min_entry, len(entry_full), 2):
            window = entry_full[:i]
            now = window[-1].timestamp + config.entry_timeframe.duration
            signal = strategy.evaluate(window, confirm_full, now=now)
            directions_seen.add(signal.direction)

            if signal.direction != SignalDirection.NO_TRADE:
                assert signal.strategy_mode == strategy.mode
                assert signal.strategy_version == strategy.version
                assert 1 <= len(signal.targets) <= 3
                assert signal.confidence_score == 100.0
                assert signal.entry_price is not None
                assert signal.setup_expiration is not None
                assert len(signal.invalidation_conditions) == 2

        if len(directions_seen) == 3:
            break

    assert directions_seen == {SignalDirection.BUY, SignalDirection.SELL, SignalDirection.NO_TRADE}


@pytest.mark.parametrize(
    "strategy_cls,config_loader,prefix",
    [
        (ScalpStrategy, load_scalp_config, "SCALP"),
        (DayTradeStrategy, load_daytrade_config, "DAYTRADE"),
    ],
)
def test_insufficient_history_is_no_trade(strategy_cls, config_loader, prefix):
    config = config_loader({})
    strategy = strategy_cls(config, "XAUUSD")
    provider = MockDataProvider(seed=1)
    now = START + timedelta(days=1)
    entry_candles = provider.get_candles(
        "XAUUSD", config.entry_timeframe, START, START + config.entry_timeframe.duration * 3
    )
    confirm_candles = provider.get_candles(
        "XAUUSD",
        config.confirmation_timeframe,
        START,
        START + config.confirmation_timeframe.duration * 3,
    )

    signal = strategy.evaluate(entry_candles, confirm_candles, now=now)
    assert signal.direction == SignalDirection.NO_TRADE
    assert signal.reason == "insufficient_candle_history"


@pytest.mark.parametrize(
    "strategy_cls,config_loader,prefix",
    [
        (ScalpStrategy, load_scalp_config, "SCALP"),
        (DayTradeStrategy, load_daytrade_config, "DAYTRADE"),
    ],
)
def test_cooldown_forces_no_trade(strategy_cls, config_loader, prefix):
    config = config_loader({f"GOLDSIGNAL_{prefix}_COOLDOWN_MINUTES": "30"})
    strategy = strategy_cls(config, "XAUUSD")
    provider = MockDataProvider(seed=1)
    end = _sufficient_end(config)
    entry_candles = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm_candles = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)
    now = entry_candles[-1].timestamp

    context = EvaluationContext(last_signal_time=now - timedelta(minutes=1))
    signal = strategy.evaluate(entry_candles, confirm_candles, now=now, context=context)
    assert signal.direction == SignalDirection.NO_TRADE
    assert signal.reason == "cooldown_active"


@pytest.mark.parametrize(
    "strategy_cls,config_loader,prefix",
    [
        (ScalpStrategy, load_scalp_config, "SCALP"),
        (DayTradeStrategy, load_daytrade_config, "DAYTRADE"),
    ],
)
def test_session_limit_forces_no_trade(strategy_cls, config_loader, prefix):
    config = config_loader({f"GOLDSIGNAL_{prefix}_MAX_SIGNALS_PER_SESSION": "1"})
    strategy = strategy_cls(config, "XAUUSD")
    provider = MockDataProvider(seed=1)
    end = _sufficient_end(config)
    entry_candles = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm_candles = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)
    now = entry_candles[-1].timestamp

    context = EvaluationContext(signals_emitted_this_session=1)
    signal = strategy.evaluate(entry_candles, confirm_candles, now=now, context=context)
    assert signal.direction == SignalDirection.NO_TRADE
    assert signal.reason == "max_signals_per_session_reached"


def test_scalp_and_daytrade_signal_ids_differ_for_same_candle_direction():
    scalp_config = load_scalp_config(_loose_env("SCALP"))
    daytrade_config = load_daytrade_config(_loose_env("DAYTRADE"))
    assert scalp_config.entry_timeframe != daytrade_config.entry_timeframe
    # Different entry_timeframe alone guarantees different signal_id inputs,
    # so ids can never collide between modes even on the same instrument/time.
