"""End-to-end tests for the A+/A/WATCHLIST/NO_TRADE classifier.

Follows the same approach as test_evaluation_trace.py / test_strategies.py:
hand-crafting exact candle sequences that satisfy the full multi-indicator
pipeline is fragile, so a long loosened-threshold scan over synthetic
mock data is used to exercise all four grades and check invariants that
must hold regardless of which candles produced them.
"""

from datetime import UTC, datetime

from goldsignal.config import load_scalp_config
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.models.signal import SignalDirection, StrategyMode
from goldsignal.strategy.base import EvaluationContext
from goldsignal.strategy.classification import SignalGrade, classify

START = datetime(2026, 1, 1, tzinfo=UTC)

_LOOSE_OVERRIDES = {
    "COOLDOWN_MINUTES": "0",
    "MAX_SIGNALS_PER_SESSION": "10000",
    "ESTIMATED_SPREAD": "0.0",
    "ESTIMATED_SLIPPAGE": "0.0",
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
    # Wider than the other strategy tests' usual 8 — a continuation move by
    # definition has already pushed past nearby resistance, so a short
    # lookback rarely finds any structural target still ahead of price.
    "STRUCTURE_LOOKBACK": "20",
    "CONTINUATION_BREAKOUT_MIN_ATR_MULTIPLE": "0.02",
    "CONTINUATION_MIN_BODY_RATIO": "0.3",
    "CONTINUATION_CLOSE_POSITION_RATIO": "0.4",
    "CONTINUATION_MAX_RANGE_ATR_MULTIPLE": "5.0",
    "CONTINUATION_CONFIRMATION_TOLERANCE_ATR_FRACTION": "1.0",
}


def _loose_env():
    return {f"GOLDSIGNAL_SCALP_{k}": v for k, v in _LOOSE_OVERRIDES.items()}


def test_classification_scan_hits_all_grades_and_invariants_hold():
    config = load_scalp_config(_loose_env())
    provider = MockDataProvider(seed=4, base_price=2400.0, volatility=6.0)
    end = START + config.entry_timeframe.duration * 600
    entry_full = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm_full = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)

    grades_seen: set[SignalGrade] = set()
    pending = None
    context = EvaluationContext()

    for i in range(60, len(entry_full), 1):
        window = entry_full[: i + 1]
        now = window[-1].timestamp + config.entry_timeframe.duration
        result = classify(
            mode=StrategyMode.SCALP,
            version="scalp_test_v1",
            config=config,
            instrument="XAUUSD",
            entry_candles=window,
            confirmation_candles=confirm_full,
            now=now,
            context=context,
            pending=pending,
        )
        grades_seen.add(result.grade)
        pending = result.pending

        if result.grade == SignalGrade.A_PLUS:
            assert result.signal is not None
            assert result.signal.direction != SignalDirection.NO_TRADE
            assert result.signal.confidence_score == 100.0
            assert result.pending is None
            context = EvaluationContext(
                last_signal_time=result.signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )
        elif result.grade == SignalGrade.A:
            assert result.signal is not None
            assert result.signal.direction != SignalDirection.NO_TRADE
            assert len(result.signal.targets) >= 1
            assert "two_candle_continuation" in result.signal.strategy_version
            assert result.pending is None
            context = EvaluationContext(
                last_signal_time=result.signal.signal_timestamp,
                signals_emitted_this_session=context.signals_emitted_this_session + 1,
            )
        elif result.grade == SignalGrade.WATCHLIST:
            assert result.signal is None
            assert result.pending is not None
        else:
            assert result.grade == SignalGrade.NO_TRADE
            assert result.signal is None

        if len(grades_seen) == 4:
            break

    assert grades_seen == {
        SignalGrade.A_PLUS,
        SignalGrade.A,
        SignalGrade.WATCHLIST,
        SignalGrade.NO_TRADE,
    }


def test_a_plus_and_a_signals_are_versioned_differently():
    """A+ signals use the base strategy_version; A signals are tagged so
    they can never be confused with (or accidentally combined into) A+
    statistics downstream.
    """
    config = load_scalp_config(_loose_env())
    provider = MockDataProvider(seed=4, base_price=2400.0, volatility=6.0)
    end = START + config.entry_timeframe.duration * 600
    entry_full = provider.get_candles("XAUUSD", config.entry_timeframe, START, end)
    confirm_full = provider.get_candles("XAUUSD", config.confirmation_timeframe, START, end)

    pending = None
    seen_a_plus_version = None
    seen_a_version = None
    for i in range(60, len(entry_full), 1):
        window = entry_full[: i + 1]
        now = window[-1].timestamp + config.entry_timeframe.duration
        result = classify(
            mode=StrategyMode.SCALP,
            version="scalp_test_v1",
            config=config,
            instrument="XAUUSD",
            entry_candles=window,
            confirmation_candles=confirm_full,
            now=now,
            pending=pending,
        )
        pending = result.pending
        if result.grade == SignalGrade.A_PLUS:
            seen_a_plus_version = result.signal.strategy_version
        elif result.grade == SignalGrade.A:
            seen_a_version = result.signal.strategy_version
        if seen_a_plus_version and seen_a_version:
            break

    assert seen_a_plus_version == "scalp_test_v1"
    assert seen_a_version == "scalp_test_v1+two_candle_continuation"
    assert seen_a_plus_version != seen_a_version
