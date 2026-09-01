"""Day-trade strategy: 15-minute entries confirmed on the 1-hour chart."""

from __future__ import annotations

from datetime import datetime

from goldsignal.config import ModeConfig
from goldsignal.models.candle import Candle
from goldsignal.models.signal import StrategyMode, StrategySignal
from goldsignal.strategy._common import evaluate_trend_ema_rsi_atr
from goldsignal.strategy.base import EvaluationContext

STRATEGY_VERSION = "daytrade_ema_rsi_atr_v1"


class DayTradeStrategy:
    mode = StrategyMode.DAY_TRADE
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
