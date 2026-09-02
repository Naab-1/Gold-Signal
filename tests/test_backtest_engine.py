from datetime import UTC, datetime, timedelta

import pytest

from goldsignal.backtest.engine import simulate_trade_management
from goldsignal.backtest.models import OpenedTrade
from goldsignal.models.candle import Candle, Timeframe
from goldsignal.models.signal import (
    EntryOrderType,
    ProfitTarget,
    SignalDirection,
    StrategyMode,
    StrategySignal,
)
from goldsignal.strategy.trade_management import (
    BreakevenRule,
    BreakevenTrigger,
    TpShortfallHandling,
    TradeManagementPreset,
    resolve_allocations,
)

START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(i, o, h, low, c):
    return Candle(
        timestamp=START + timedelta(hours=i), open=o, high=h, low=low, close=c, volume=100
    )


def _signal(*, stop_loss, targets, entry_price=100.0):
    ts = START
    return StrategySignal(
        signal_id="sig1",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.BUY,
        signal_timestamp=ts,
        entry_price=entry_price,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=stop_loss,
        targets=targets,
        setup_expiration=ts + timedelta(hours=1),
        invalidation_conditions=["x"],
        estimated_spread=0.0,
        estimated_slippage=0.0,
    )


def _opened(signal, fill_price=100.0, fill_candle_index=0, gapped=False):
    return OpenedTrade(
        signal=signal,
        fill_timestamp=START,
        fill_price=fill_price,
        fill_candle_index=fill_candle_index,
        gapped_through_stop=gapped,
    )


NO_BREAKEVEN = BreakevenRule()


def test_simple_stop_no_target_touched():
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=103.0, r_multiple=0.6)]
    )
    opened = _opened(signal)
    candles = [_candle(0, 100, 101, 94, 94.5)]  # touches stop=95 immediately, no TP1 touch

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
    )

    assert trade.exit_reason == "stop"
    assert trade.target_fills == []
    assert trade.is_full_stop is True
    assert trade.realized_r == -1.0


def test_gapped_through_stop_is_immediate_full_loss():
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=103.0, r_multiple=0.6)]
    )
    opened = _opened(signal, fill_price=94.0, gapped=True)
    candles = [_candle(0, 94, 96, 93, 95)]  # irrelevant, short-circuited

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
    )

    assert trade.exit_reason == "stop"
    assert trade.is_full_stop is True
    assert trade.realized_r == -1.0
    assert trade.target_fills == []


def test_same_candle_collision_stop_wins_conservatively():
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=103.0, r_multiple=0.6)]
    )
    opened = _opened(signal)
    # one candle's range touches both the stop (low=94) and TP1 (high=104)
    candles = [_candle(0, 100, 104, 94, 100)]

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
    )

    assert trade.exit_reason == "stop"
    assert trade.target_fills == []  # TP1 must NOT fill despite being touched in range
    assert trade.realized_r == -1.0


def test_two_targets_hit_sequentially_with_breakeven_after_tp1():
    targets = [
        ProfitTarget(label="TP1", price=103.0, r_multiple=0.6),
        ProfitTarget(label="TP2", price=106.0, r_multiple=1.2),
    ]
    signal = _signal(stop_loss=95.0, targets=targets)
    opened = _opened(signal)
    candles = [
        _candle(0, 100, 101, 99, 100.5),  # fill candle, no touches
        _candle(1, 100.5, 103.5, 99, 103),  # TP1 touched
        _candle(2, 101, 102, 100.5, 101),  # pullback, stays above breakeven stop (100)
        _candle(3, 101, 106.5, 100.5, 106.2),  # TP2 touched -> fully closed
    ]
    breakeven_rule = BreakevenRule(trigger=BreakevenTrigger.AFTER_TP1_CONFIRMED)

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.CONSERVATIVE,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=breakeven_rule,
        transaction_cost=1.0,
    )

    allocations = resolve_allocations(
        TradeManagementPreset.CONSERVATIVE, 2, TpShortfallHandling.NORMALIZE
    )
    risk = 5.0
    expected_r = allocations[0] * (0.6) + allocations[1] * (1.2) - (1.0 / risk)

    assert trade.exit_reason == "all_targets_hit"
    assert [tf.label for tf in trade.target_fills] == ["TP1", "TP2"]
    assert trade.breakeven_triggered is True
    assert len(trade.stop_adjustments) == 1
    assert trade.stop_adjustments[0].new_stop == 100.0
    assert trade.is_full_stop is False
    assert trade.realized_r == expected_r


def test_breakeven_stop_after_tp1_when_price_reverses():
    targets = [
        ProfitTarget(label="TP1", price=103.0, r_multiple=0.6),
        ProfitTarget(label="TP2", price=106.0, r_multiple=1.2),
    ]
    signal = _signal(stop_loss=95.0, targets=targets)
    opened = _opened(signal)
    candles = [
        _candle(0, 100, 101, 99, 100.5),
        _candle(1, 100.5, 103.5, 99, 103),  # TP1 touched, breakeven stop set to 100
        _candle(2, 101, 101.5, 99, 99.5),  # reverses and hits breakeven stop (100)
    ]
    breakeven_rule = BreakevenRule(trigger=BreakevenTrigger.AFTER_TP1_CONFIRMED)

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.CONSERVATIVE,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=breakeven_rule,
        transaction_cost=0.0,
    )

    assert trade.exit_reason == "breakeven_stop"
    assert [tf.label for tf in trade.target_fills] == ["TP1"]
    assert trade.exit_price == 100.0


def test_data_ends_while_open_marks_to_market():
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=110.0, r_multiple=3.0)]
    )
    opened = _opened(signal)
    candles = [
        _candle(0, 100, 101, 99, 100.5),
        _candle(1, 100.5, 102, 100, 101.5),
    ]

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
    )

    assert trade.exit_reason == "data_end_mark_to_market"
    assert trade.exit_price == 101.5
    assert trade.target_fills == []


# --- Exit-side spread/slippage cost (audit finding: entry charged half-
# spread+slippage via entry_fill_price, but exits charged nothing beyond a
# flat transaction_cost -- not duplicated, but under-counted real
# round-trip cost). estimated_spread/estimated_slippage default to 0.0 so
# every test above this line is unaffected. ---


def test_stop_exit_charges_half_spread_plus_slippage():
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=103.0, r_multiple=0.6)]
    )
    opened = _opened(signal)  # fill_price=100, risk=5
    candles = [_candle(0, 100, 101, 94, 94.5)]

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
        estimated_spread=1.0,
        estimated_slippage=0.5,
    )

    # exit_adverse = 1.0/2 + 0.5 = 1.0; additional cost = 1.0/risk(5) = 0.2
    assert trade.exit_price == 94.0  # stop(95) - exit_adverse(1.0)
    assert trade.realized_r == -1.2


def test_gapped_through_stop_also_charges_exit_adverse():
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=103.0, r_multiple=0.6)]
    )
    opened = _opened(signal, fill_price=94.0, gapped=True)  # risk = |94-95| = 1
    candles = [_candle(0, 94, 96, 93, 95)]

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
        estimated_spread=0.2,
        estimated_slippage=0.0,
    )

    # exit_adverse = 0.1; additional cost = 0.1/risk(1) = 0.1 on top of -1.0
    assert trade.realized_r == -1.1


def test_target_hit_charges_exit_adverse_on_the_realized_r_not_the_displayed_price():
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=105.0, r_multiple=1.0)]
    )
    opened = _opened(signal)  # fill_price=100, risk=5
    candles = [_candle(0, 100, 106, 100, 105.5)]  # touches TP1=105

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
        estimated_spread=1.0,
        estimated_slippage=0.0,
    )

    # The nominal target price is still shown on the fill record...
    assert trade.target_fills[0].price == 105.0
    # ...but the R actually realized reflects effective_price = 105 - 0.5 = 104.5
    expected_r_multiple = (104.5 - 100) / 5
    assert trade.target_fills[0].r_multiple == expected_r_multiple


def test_sell_direction_exit_adverse_has_opposite_sign():
    ts = START
    signal = StrategySignal(
        signal_id="sig_sell",
        instrument="XAUUSD",
        strategy_mode=StrategyMode.SCALP,
        strategy_version="v1",
        entry_timeframe=Timeframe.M5,
        confirmation_timeframe=Timeframe.M15,
        direction=SignalDirection.SELL,
        signal_timestamp=ts,
        entry_price=100.0,
        entry_order_type=EntryOrderType.MARKET,
        stop_loss=105.0,
        targets=[ProfitTarget(label="TP1", price=90.0, r_multiple=2.0)],
        setup_expiration=ts + timedelta(hours=1),
        invalidation_conditions=["x"],
        estimated_spread=0.0,
        estimated_slippage=0.0,
    )
    opened = _opened(signal, fill_price=100.0)  # risk = |100-105| = 5
    candles = [_candle(0, 100, 106, 99, 105.5)]  # touches stop=105

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
        estimated_spread=1.0,
        estimated_slippage=0.0,
    )

    # SELL exit is a buy-to-close: adverse cost pushes the exit price UP,
    # not down -- 105 + 0.5 = 105.5, a worse (more negative) outcome.
    assert trade.exit_price == 105.5
    assert trade.realized_r == -1.1


def test_exit_adverse_defaults_to_zero_when_not_specified():
    """Backward compatibility: callers that don't pass
    estimated_spread/estimated_slippage get exactly the old behavior.
    """
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=103.0, r_multiple=0.6)]
    )
    opened = _opened(signal)
    candles = [_candle(0, 100, 101, 94, 94.5)]

    trade = simulate_trade_management(
        opened,
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
    )

    assert trade.realized_r == -1.0


def test_exit_cost_is_charged_once_not_duplicated():
    """The audit question this whole section exists to answer: is spread
    ever charged twice? Compare a spread=0 baseline against a spread=S
    trade on an otherwise-identical stop-out -- the difference must equal
    exactly one half-spread's worth of R, not two.
    """
    signal = _signal(
        stop_loss=95.0, targets=[ProfitTarget(label="TP1", price=103.0, r_multiple=0.6)]
    )
    candles = [_candle(0, 100, 101, 94, 94.5)]

    baseline = simulate_trade_management(
        _opened(signal),
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
        estimated_spread=0.0,
        estimated_slippage=0.0,
    )
    with_spread = simulate_trade_management(
        _opened(signal),
        candles,
        preset=TradeManagementPreset.BALANCED,
        shortfall_mode=TpShortfallHandling.NORMALIZE,
        breakeven_rule=NO_BREAKEVEN,
        transaction_cost=0.0,
        estimated_spread=2.0,
        estimated_slippage=0.0,
    )

    risk = 5.0  # fill_price=100, stop=95
    expected_diff = (2.0 / 2) / risk  # half-spread only, applied once, at exit
    assert baseline.realized_r - with_spread.realized_r == pytest.approx(expected_diff)
