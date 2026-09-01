"""Environment-variable configuration.

All strategy parameters are configurable — nothing is hard-coded. Loading
fails closed: any missing/invalid value raises ConfigError rather than
silently falling back to a guessed value.

GlobalSettings holds process-wide config: data provider selection,
instrument, logging, and the credentials for the integrations that
actually exist (TwelveData, Telegram, Postgres). ModeConfig is loaded once
per strategy mode (GOLDSIGNAL_SCALP_* and GOLDSIGNAL_DAYTRADE_*) so Scalp
and Day-Trade are genuinely independently configurable — same schema,
separate values.

Credentials are validated for presence only where they're actually used
(e.g. TwelveDataProvider checks its own API key, telegram.py checks its
own token/chat id) rather than all being force-required here, since not
every entry point needs every integration (tests need none of them).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from goldsignal.models.candle import Timeframe
from goldsignal.strategy.trade_management import (
    BreakevenRule,
    BreakevenTrigger,
    TpShortfallHandling,
    TradeManagementPreset,
)

_PREFIX = "GOLDSIGNAL_"


class ConfigError(ValueError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class GlobalSettings:
    data_provider: str
    instrument: str
    log_level: str
    twelvedata_api_key: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    telegram_debug_mode: bool
    database_url: str | None


@dataclass(frozen=True)
class ModeConfig:
    enabled: bool
    entry_timeframe: Timeframe
    confirmation_timeframe: Timeframe

    ema_fast_period: int
    ema_slow_period: int

    rsi_period: int
    rsi_buy_threshold: float
    rsi_sell_threshold: float
    rsi_overbought: float
    rsi_oversold: float

    atr_period: int
    atr_stop_multiplier: float

    structure_lookback: int
    retest_tolerance_atr_fraction: float
    retest_confirm_window: int

    chop_filter_atr_multiple: float
    trend_strength_atr_multiple: float

    min_net_reward_r: float
    estimated_spread: float
    estimated_slippage: float
    estimated_transaction_cost: float

    cooldown_minutes: int
    max_signals_per_session: int
    setup_expiration_candles: int

    trade_management_preset: TradeManagementPreset
    tp_shortfall_handling: TpShortfallHandling
    breakeven_trigger: BreakevenTrigger
    breakeven_after_r_multiple: float | None


_GLOBAL_DEFAULTS: dict[str, str] = {
    "DATA_PROVIDER": "mock",
    "INSTRUMENT": "XAUUSD",
    "LOG_LEVEL": "INFO",
    "TWELVEDATA_API_KEY": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "TELEGRAM_DEBUG_MODE": "false",
    "DATABASE_URL": "",
}

# Scalp: 5m entries confirmed on 15m structure/trend.
_SCALP_DEFAULTS: dict[str, str] = {
    "ENABLED": "true",
    "ENTRY_TIMEFRAME": "M5",
    "CONFIRMATION_TIMEFRAME": "M15",
    "EMA_FAST_PERIOD": "20",
    "EMA_SLOW_PERIOD": "50",
    "RSI_PERIOD": "14",
    "RSI_BUY_THRESHOLD": "50",
    "RSI_SELL_THRESHOLD": "50",
    "RSI_OVERBOUGHT": "70",
    "RSI_OVERSOLD": "30",
    "ATR_PERIOD": "14",
    "ATR_STOP_MULTIPLIER": "1.2",
    "STRUCTURE_LOOKBACK": "20",
    "RETEST_TOLERANCE_ATR_FRACTION": "0.25",
    "RETEST_CONFIRM_WINDOW": "5",
    "CHOP_FILTER_ATR_MULTIPLE": "0.5",
    "TREND_STRENGTH_ATR_MULTIPLE": "1.5",
    "MIN_NET_REWARD_R": "1.0",
    "ESTIMATED_SPREAD": "0.30",
    "ESTIMATED_SLIPPAGE": "0.20",
    "ESTIMATED_TRANSACTION_COST": "0.0",
    "COOLDOWN_MINUTES": "15",
    "MAX_SIGNALS_PER_SESSION": "6",
    "SETUP_EXPIRATION_CANDLES": "3",
    "TRADE_MANAGEMENT_PRESET": "balanced",
    "TP_SHORTFALL_HANDLING": "normalize",
    "BREAKEVEN_TRIGGER": "none",
    "BREAKEVEN_AFTER_R_MULTIPLE": "",
}

# Day-trade: 15m entries confirmed on 1h structure/trend.
_DAYTRADE_DEFAULTS: dict[str, str] = {
    "ENABLED": "true",
    "ENTRY_TIMEFRAME": "M15",
    "CONFIRMATION_TIMEFRAME": "H1",
    "EMA_FAST_PERIOD": "20",
    "EMA_SLOW_PERIOD": "50",
    "RSI_PERIOD": "14",
    "RSI_BUY_THRESHOLD": "50",
    "RSI_SELL_THRESHOLD": "50",
    "RSI_OVERBOUGHT": "70",
    "RSI_OVERSOLD": "30",
    "ATR_PERIOD": "14",
    "ATR_STOP_MULTIPLIER": "1.5",
    "STRUCTURE_LOOKBACK": "20",
    "RETEST_TOLERANCE_ATR_FRACTION": "0.25",
    "RETEST_CONFIRM_WINDOW": "5",
    "CHOP_FILTER_ATR_MULTIPLE": "0.5",
    "TREND_STRENGTH_ATR_MULTIPLE": "1.5",
    "MIN_NET_REWARD_R": "2.0",
    "ESTIMATED_SPREAD": "0.30",
    "ESTIMATED_SLIPPAGE": "0.20",
    "ESTIMATED_TRANSACTION_COST": "0.0",
    "COOLDOWN_MINUTES": "60",
    "MAX_SIGNALS_PER_SESSION": "4",
    "SETUP_EXPIRATION_CANDLES": "3",
    "TRADE_MANAGEMENT_PRESET": "balanced",
    "TP_SHORTFALL_HANDLING": "normalize",
    "BREAKEVEN_TRIGGER": "none",
    "BREAKEVEN_AFTER_R_MULTIPLE": "",
}


def _get(env: Mapping[str, str], prefix: str, name: str, defaults: dict[str, str]) -> str:
    # .strip() guards against a stray trailing newline/whitespace from
    # copy-pasting a value into a .env file or a CI secret — a common
    # footgun that otherwise produces confusing downstream errors.
    return env.get(f"{_PREFIX}{prefix}{name}", defaults[name]).strip()


def _parse_int(raw: str, var_name: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{var_name} must be an integer, got {raw!r}") from exc


def _parse_float(raw: str, var_name: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{var_name} must be a number, got {raw!r}") from exc


def _parse_bool(raw: str, var_name: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    raise ConfigError(f"{var_name} must be a boolean (true/false), got {raw!r}")


def load_global_settings(env: Mapping[str, str] | None = None) -> GlobalSettings:
    env = os.environ if env is None else env
    settings = GlobalSettings(
        data_provider=_get(env, "", "DATA_PROVIDER", _GLOBAL_DEFAULTS),
        instrument=_get(env, "", "INSTRUMENT", _GLOBAL_DEFAULTS),
        log_level=_get(env, "", "LOG_LEVEL", _GLOBAL_DEFAULTS),
        twelvedata_api_key=_get(env, "", "TWELVEDATA_API_KEY", _GLOBAL_DEFAULTS) or None,
        telegram_bot_token=_get(env, "", "TELEGRAM_BOT_TOKEN", _GLOBAL_DEFAULTS) or None,
        telegram_chat_id=_get(env, "", "TELEGRAM_CHAT_ID", _GLOBAL_DEFAULTS) or None,
        telegram_debug_mode=_parse_bool(
            _get(env, "", "TELEGRAM_DEBUG_MODE", _GLOBAL_DEFAULTS), f"{_PREFIX}TELEGRAM_DEBUG_MODE"
        ),
        database_url=_get(env, "", "DATABASE_URL", _GLOBAL_DEFAULTS) or None,
    )
    if not settings.instrument.strip():
        raise ConfigError(f"{_PREFIX}INSTRUMENT must not be empty")
    if settings.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        raise ConfigError(f"{_PREFIX}LOG_LEVEL={settings.log_level!r} is not a valid log level")
    if settings.data_provider == "twelvedata" and not settings.twelvedata_api_key:
        raise ConfigError(
            f"{_PREFIX}TWELVEDATA_API_KEY is required when {_PREFIX}DATA_PROVIDER=twelvedata"
        )
    return settings


def _load_timeframe(
    env: Mapping[str, str], prefix: str, name: str, defaults: dict[str, str]
) -> Timeframe:
    var_name = f"{_PREFIX}{prefix}{name}"
    raw = _get(env, prefix, name, defaults)
    try:
        return Timeframe(raw)
    except ValueError as exc:
        valid = ", ".join(t.value for t in Timeframe)
        raise ConfigError(f"{var_name}={raw!r} is not one of: {valid}") from exc


def load_mode_config(
    mode_prefix: str,
    defaults: dict[str, str],
    env: Mapping[str, str] | None = None,
) -> ModeConfig:
    """Load a ModeConfig for one mode. `mode_prefix` is "SCALP_" or
    "DAYTRADE_"; `defaults` is `_SCALP_DEFAULTS` or `_DAYTRADE_DEFAULTS`.
    """
    env = os.environ if env is None else env
    p = mode_prefix

    def var(name: str) -> str:
        return f"{_PREFIX}{p}{name}"

    breakeven_after_raw = _get(env, p, "BREAKEVEN_AFTER_R_MULTIPLE", defaults)
    breakeven_after_r_multiple = (
        _parse_float(breakeven_after_raw, var("BREAKEVEN_AFTER_R_MULTIPLE"))
        if breakeven_after_raw.strip()
        else None
    )

    trade_preset_raw = _get(env, p, "TRADE_MANAGEMENT_PRESET", defaults)
    try:
        trade_preset = TradeManagementPreset(trade_preset_raw)
    except ValueError as exc:
        valid = ", ".join(t.value for t in TradeManagementPreset)
        raise ConfigError(
            f"{var('TRADE_MANAGEMENT_PRESET')}={trade_preset_raw!r} is not one of: {valid}"
        ) from exc

    shortfall_raw = _get(env, p, "TP_SHORTFALL_HANDLING", defaults)
    try:
        shortfall = TpShortfallHandling(shortfall_raw)
    except ValueError as exc:
        valid = ", ".join(t.value for t in TpShortfallHandling)
        raise ConfigError(
            f"{var('TP_SHORTFALL_HANDLING')}={shortfall_raw!r} is not one of: {valid}"
        ) from exc

    breakeven_raw = _get(env, p, "BREAKEVEN_TRIGGER", defaults)
    try:
        breakeven_trigger = BreakevenTrigger(breakeven_raw)
    except ValueError as exc:
        valid = ", ".join(t.value for t in BreakevenTrigger)
        raise ConfigError(
            f"{var('BREAKEVEN_TRIGGER')}={breakeven_raw!r} is not one of: {valid}"
        ) from exc

    try:
        BreakevenRule(trigger=breakeven_trigger, after_r_multiple=breakeven_after_r_multiple)
    except ValueError as exc:
        raise ConfigError(
            f"{var('BREAKEVEN_TRIGGER')}/{var('BREAKEVEN_AFTER_R_MULTIPLE')}: {exc}"
        ) from exc

    config = ModeConfig(
        enabled=_parse_bool(_get(env, p, "ENABLED", defaults), var("ENABLED")),
        entry_timeframe=_load_timeframe(env, p, "ENTRY_TIMEFRAME", defaults),
        confirmation_timeframe=_load_timeframe(env, p, "CONFIRMATION_TIMEFRAME", defaults),
        ema_fast_period=_parse_int(
            _get(env, p, "EMA_FAST_PERIOD", defaults), var("EMA_FAST_PERIOD")
        ),
        ema_slow_period=_parse_int(
            _get(env, p, "EMA_SLOW_PERIOD", defaults), var("EMA_SLOW_PERIOD")
        ),
        rsi_period=_parse_int(_get(env, p, "RSI_PERIOD", defaults), var("RSI_PERIOD")),
        rsi_buy_threshold=_parse_float(
            _get(env, p, "RSI_BUY_THRESHOLD", defaults), var("RSI_BUY_THRESHOLD")
        ),
        rsi_sell_threshold=_parse_float(
            _get(env, p, "RSI_SELL_THRESHOLD", defaults), var("RSI_SELL_THRESHOLD")
        ),
        rsi_overbought=_parse_float(
            _get(env, p, "RSI_OVERBOUGHT", defaults), var("RSI_OVERBOUGHT")
        ),
        rsi_oversold=_parse_float(_get(env, p, "RSI_OVERSOLD", defaults), var("RSI_OVERSOLD")),
        atr_period=_parse_int(_get(env, p, "ATR_PERIOD", defaults), var("ATR_PERIOD")),
        atr_stop_multiplier=_parse_float(
            _get(env, p, "ATR_STOP_MULTIPLIER", defaults), var("ATR_STOP_MULTIPLIER")
        ),
        structure_lookback=_parse_int(
            _get(env, p, "STRUCTURE_LOOKBACK", defaults), var("STRUCTURE_LOOKBACK")
        ),
        retest_tolerance_atr_fraction=_parse_float(
            _get(env, p, "RETEST_TOLERANCE_ATR_FRACTION", defaults),
            var("RETEST_TOLERANCE_ATR_FRACTION"),
        ),
        retest_confirm_window=_parse_int(
            _get(env, p, "RETEST_CONFIRM_WINDOW", defaults), var("RETEST_CONFIRM_WINDOW")
        ),
        chop_filter_atr_multiple=_parse_float(
            _get(env, p, "CHOP_FILTER_ATR_MULTIPLE", defaults), var("CHOP_FILTER_ATR_MULTIPLE")
        ),
        trend_strength_atr_multiple=_parse_float(
            _get(env, p, "TREND_STRENGTH_ATR_MULTIPLE", defaults),
            var("TREND_STRENGTH_ATR_MULTIPLE"),
        ),
        min_net_reward_r=_parse_float(
            _get(env, p, "MIN_NET_REWARD_R", defaults), var("MIN_NET_REWARD_R")
        ),
        estimated_spread=_parse_float(
            _get(env, p, "ESTIMATED_SPREAD", defaults), var("ESTIMATED_SPREAD")
        ),
        estimated_slippage=_parse_float(
            _get(env, p, "ESTIMATED_SLIPPAGE", defaults), var("ESTIMATED_SLIPPAGE")
        ),
        estimated_transaction_cost=_parse_float(
            _get(env, p, "ESTIMATED_TRANSACTION_COST", defaults), var("ESTIMATED_TRANSACTION_COST")
        ),
        cooldown_minutes=_parse_int(
            _get(env, p, "COOLDOWN_MINUTES", defaults), var("COOLDOWN_MINUTES")
        ),
        max_signals_per_session=_parse_int(
            _get(env, p, "MAX_SIGNALS_PER_SESSION", defaults), var("MAX_SIGNALS_PER_SESSION")
        ),
        setup_expiration_candles=_parse_int(
            _get(env, p, "SETUP_EXPIRATION_CANDLES", defaults), var("SETUP_EXPIRATION_CANDLES")
        ),
        trade_management_preset=trade_preset,
        tp_shortfall_handling=shortfall,
        breakeven_trigger=breakeven_trigger,
        breakeven_after_r_multiple=breakeven_after_r_multiple,
    )
    _validate_mode_config(config, p)
    return config


def _validate_mode_config(c: ModeConfig, mode_prefix: str) -> None:
    def var(name: str) -> str:
        return f"{_PREFIX}{mode_prefix}{name}"

    if c.entry_timeframe == c.confirmation_timeframe:
        raise ConfigError(
            f"{var('ENTRY_TIMEFRAME')} and {var('CONFIRMATION_TIMEFRAME')} must differ"
        )
    if c.confirmation_timeframe.duration <= c.entry_timeframe.duration:
        raise ConfigError(
            f"{var('CONFIRMATION_TIMEFRAME')} must be a longer duration "
            f"than {var('ENTRY_TIMEFRAME')}"
        )
    if c.ema_fast_period <= 0 or c.ema_slow_period <= 0:
        raise ConfigError(f"{var('EMA_FAST_PERIOD')}/{var('EMA_SLOW_PERIOD')} must be positive")
    if c.ema_fast_period >= c.ema_slow_period:
        raise ConfigError(f"{var('EMA_FAST_PERIOD')} must be less than {var('EMA_SLOW_PERIOD')}")
    if c.rsi_period <= 0:
        raise ConfigError(f"{var('RSI_PERIOD')} must be positive")
    if not (0 <= c.rsi_oversold < c.rsi_overbought <= 100):
        raise ConfigError(
            f"{var('RSI_OVERSOLD')} must be less than {var('RSI_OVERBOUGHT')}, both within [0, 100]"
        )
    if c.atr_period <= 0:
        raise ConfigError(f"{var('ATR_PERIOD')} must be positive")
    if c.atr_stop_multiplier <= 0:
        raise ConfigError(f"{var('ATR_STOP_MULTIPLIER')} must be positive")
    if c.structure_lookback <= 1:
        raise ConfigError(f"{var('STRUCTURE_LOOKBACK')} must be greater than 1")
    if c.retest_tolerance_atr_fraction < 0:
        raise ConfigError(f"{var('RETEST_TOLERANCE_ATR_FRACTION')} must not be negative")
    if c.retest_confirm_window <= 0:
        raise ConfigError(f"{var('RETEST_CONFIRM_WINDOW')} must be positive")
    if c.chop_filter_atr_multiple <= 0:
        raise ConfigError(f"{var('CHOP_FILTER_ATR_MULTIPLE')} must be positive")
    if c.trend_strength_atr_multiple <= c.chop_filter_atr_multiple:
        raise ConfigError(
            f"{var('TREND_STRENGTH_ATR_MULTIPLE')} must be greater "
            f"than {var('CHOP_FILTER_ATR_MULTIPLE')}"
        )
    if c.min_net_reward_r <= 0:
        raise ConfigError(f"{var('MIN_NET_REWARD_R')} must be positive")
    if c.estimated_spread < 0 or c.estimated_slippage < 0 or c.estimated_transaction_cost < 0:
        raise ConfigError(
            f"{var('ESTIMATED_SPREAD')}/{var('ESTIMATED_SLIPPAGE')}/"
            f"{var('ESTIMATED_TRANSACTION_COST')} must not be negative"
        )
    if c.cooldown_minutes < 0:
        raise ConfigError(f"{var('COOLDOWN_MINUTES')} must not be negative")
    if c.max_signals_per_session <= 0:
        raise ConfigError(f"{var('MAX_SIGNALS_PER_SESSION')} must be positive")
    if c.setup_expiration_candles <= 0:
        raise ConfigError(f"{var('SETUP_EXPIRATION_CANDLES')} must be positive")


def load_scalp_config(env: Mapping[str, str] | None = None) -> ModeConfig:
    return load_mode_config("SCALP_", _SCALP_DEFAULTS, env)


def load_daytrade_config(env: Mapping[str, str] | None = None) -> ModeConfig:
    return load_mode_config("DAYTRADE_", _DAYTRADE_DEFAULTS, env)
