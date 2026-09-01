"""Scalp strategy: 5-minute entries confirmed on the 15-minute chart.

1-minute scalping is deliberately out of scope for now — execution
latency, spread, slippage, and noise make backtests at that timeframe
unrealistic (see the plan/README limitations section).
"""

from __future__ import annotations

from datetime import datetime

from goldsignal.config import ModeConfig
from goldsignal.models.candle import Candle
from goldsignal.models.signal import StrategyMode, StrategySignal
from goldsignal.strategy._common import evaluate_trend_ema_rsi_atr
from goldsignal.strategy.base import EvaluationContext

STRATEGY_VERSION = "scalp_ema_rsi_atr_v1"


class ScalpStrategy:
    mode = StrategyMode.SCALP
    version = STRATEGY_VERSION

    def __init__(self, config: ModeConfig, instrument: str):
        self.config = config
        self.instrument = instrument

    def evaluate(
        self,
        entry_candles: list[Candle],
        confirmation_candles: list[Candle],
        *,
        now: datetime,
        context: EvaluationContext | None = None,
    ) -> StrategySignal:
        return evaluate_trend_ema_rsi_atr(
            mode=self.mode,
            version=self.version,
            config=self.config,
            instrument=self.instrument,
            entry_candles=entry_candles,
            confirmation_candles=confirmation_candles,
            now=now,
            context=context,
        )
