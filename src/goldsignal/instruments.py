"""Per-instrument profiles: the numeric/display facts that genuinely vary
by instrument and that `ModeConfig` deliberately does not capture.

Almost every `ModeConfig` numeric field (`atr_stop_multiplier`,
`chop_filter_atr_multiple`, `min_net_reward_r`, every
`continuation_*_atr_multiple` field, ...) is an ATR-relative multiplier or
an R-multiple — already instrument-agnostic by construction, since it
scales with each instrument's own volatility rather than assuming a fixed
price distance. The only fields that are genuinely tied to XAU/USD's
~$2400 price scale are `estimated_spread`/`estimated_slippage`/
`estimated_transaction_cost` (absolute price units). Everything else here
(precision, pip/tick size, max spread, contract size, broker-price
tolerance) is new — it never existed before this expansion.

Starting numeric defaults for EUR/USD, GBP/USD, and USD/JPY below are
reasonable retail-typical values, NOT live-verified against any specific
broker or venue — verify them against your own demo broker before relying
on the warnings they drive (e.g. `analysis.cli quotes`'s spread checks).
XAU/USD's defaults exactly reproduce today's existing `ModeConfig`
defaults, so `effective_mode_config` is a strict no-op for gold.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping

from goldsignal.config import ConfigError, ModeConfig, _get, _parse_float, _parse_int

INSTRUMENT_CODES: tuple[str, ...] = ("XAUUSD", "EURUSD", "GBPUSD", "USDJPY")

_NONE_SENTINEL = "none"


@dataclasses.dataclass(frozen=True)
class InstrumentProfile:
    code: str
    provider_symbol: str
    display_symbol: str
    decimal_precision: int
    pip_size: float
    tick_size: float
    contract_size: float | None
    typical_spread: float
    max_permitted_spread: float
    typical_slippage: float
    transaction_cost: float
    broker_price_tolerance: float
    primary_sessions: tuple[str, ...]
    cooldown_minutes_override: int | None = None
    atr_stop_multiplier_override: float | None = None
    min_net_reward_r_override: float | None = None


_DEFAULTS: dict[str, dict[str, str]] = {
    "XAUUSD": {
        "PROVIDER_SYMBOL": "XAUUSD",
        "DISPLAY_SYMBOL": "XAU/USD",
        "DECIMAL_PRECISION": "2",
        "PIP_SIZE": "0.01",
        "TICK_SIZE": "0.01",
        "CONTRACT_SIZE": "100",
        "TYPICAL_SPREAD": "0.30",
        "MAX_PERMITTED_SPREAD": "1.00",
        "TYPICAL_SLIPPAGE": "0.20",
        "TRANSACTION_COST": "0.0",
        "BROKER_PRICE_TOLERANCE": "0.50",
        "PRIMARY_SESSIONS": "London,New York",
        "COOLDOWN_MINUTES_OVERRIDE": _NONE_SENTINEL,
        "ATR_STOP_MULTIPLIER_OVERRIDE": _NONE_SENTINEL,
        "MIN_NET_REWARD_R_OVERRIDE": _NONE_SENTINEL,
    },
    "EURUSD": {
        "PROVIDER_SYMBOL": "EURUSD",
        "DISPLAY_SYMBOL": "EUR/USD",
        "DECIMAL_PRECISION": "5",
        "PIP_SIZE": "0.0001",
        "TICK_SIZE": "0.00001",
        "CONTRACT_SIZE": "100000",
        "TYPICAL_SPREAD": "0.0001",
        "MAX_PERMITTED_SPREAD": "0.0003",
        "TYPICAL_SLIPPAGE": "0.00005",
        "TRANSACTION_COST": "0.0",
        "BROKER_PRICE_TOLERANCE": "0.0005",
        "PRIMARY_SESSIONS": "London,New York",
        "COOLDOWN_MINUTES_OVERRIDE": _NONE_SENTINEL,
        "ATR_STOP_MULTIPLIER_OVERRIDE": _NONE_SENTINEL,
        "MIN_NET_REWARD_R_OVERRIDE": _NONE_SENTINEL,
    },
    "GBPUSD": {
        "PROVIDER_SYMBOL": "GBPUSD",
        "DISPLAY_SYMBOL": "GBP/USD",
        "DECIMAL_PRECISION": "5",
        "PIP_SIZE": "0.0001",
        "TICK_SIZE": "0.00001",
        "CONTRACT_SIZE": "100000",
        "TYPICAL_SPREAD": "0.00015",
        "MAX_PERMITTED_SPREAD": "0.0004",
        "TYPICAL_SLIPPAGE": "0.00007",
        "TRANSACTION_COST": "0.0",
        "BROKER_PRICE_TOLERANCE": "0.0006",
        "PRIMARY_SESSIONS": "London,New York",
        "COOLDOWN_MINUTES_OVERRIDE": _NONE_SENTINEL,
        "ATR_STOP_MULTIPLIER_OVERRIDE": _NONE_SENTINEL,
        "MIN_NET_REWARD_R_OVERRIDE": _NONE_SENTINEL,
    },
    "USDJPY": {
        "PROVIDER_SYMBOL": "USDJPY",
        "DISPLAY_SYMBOL": "USD/JPY",
        "DECIMAL_PRECISION": "3",
        "PIP_SIZE": "0.01",
        "TICK_SIZE": "0.001",
        "CONTRACT_SIZE": "100000",
        "TYPICAL_SPREAD": "0.01",
        "MAX_PERMITTED_SPREAD": "0.03",
        "TYPICAL_SLIPPAGE": "0.005",
        "TRANSACTION_COST": "0.0",
        "BROKER_PRICE_TOLERANCE": "0.02",
        "PRIMARY_SESSIONS": "Tokyo,London,New York",
        "COOLDOWN_MINUTES_OVERRIDE": _NONE_SENTINEL,
        "ATR_STOP_MULTIPLIER_OVERRIDE": _NONE_SENTINEL,
        "MIN_NET_REWARD_R_OVERRIDE": _NONE_SENTINEL,
    },
}


def _parse_optional_float(raw: str, var_name: str) -> float | None:
    if raw.strip().lower() == _NONE_SENTINEL:
        return None
    return _parse_float(raw, var_name)


def _parse_optional_int(raw: str, var_name: str) -> int | None:
    if raw.strip().lower() == _NONE_SENTINEL:
        return None
    return _parse_int(raw, var_name)


def _parse_sessions(raw: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def load_instrument_profile(code: str, env: Mapping[str, str] | None = None) -> InstrumentProfile:
    if code not in _DEFAULTS:
        raise ConfigError(f"unknown instrument code {code!r}; expected one of {INSTRUMENT_CODES}")
    env = os.environ if env is None else env
    defaults = _DEFAULTS[code]
    prefix = f"{code}_"

    def var(name: str) -> str:
        return f"GOLDSIGNAL_{prefix}{name}"

    contract_size_raw = _get(env, prefix, "CONTRACT_SIZE", defaults)
    profile = InstrumentProfile(
        code=code,
        provider_symbol=_get(env, prefix, "PROVIDER_SYMBOL", defaults),
        display_symbol=_get(env, prefix, "DISPLAY_SYMBOL", defaults),
        decimal_precision=_parse_int(
            _get(env, prefix, "DECIMAL_PRECISION", defaults), var("DECIMAL_PRECISION")
        ),
        pip_size=_parse_float(_get(env, prefix, "PIP_SIZE", defaults), var("PIP_SIZE")),
        tick_size=_parse_float(_get(env, prefix, "TICK_SIZE", defaults), var("TICK_SIZE")),
        contract_size=_parse_optional_float(contract_size_raw, var("CONTRACT_SIZE")),
        typical_spread=_parse_float(
            _get(env, prefix, "TYPICAL_SPREAD", defaults), var("TYPICAL_SPREAD")
        ),
        max_permitted_spread=_parse_float(
            _get(env, prefix, "MAX_PERMITTED_SPREAD", defaults), var("MAX_PERMITTED_SPREAD")
        ),
        typical_slippage=_parse_float(
            _get(env, prefix, "TYPICAL_SLIPPAGE", defaults), var("TYPICAL_SLIPPAGE")
        ),
        transaction_cost=_parse_float(
            _get(env, prefix, "TRANSACTION_COST", defaults), var("TRANSACTION_COST")
        ),
        broker_price_tolerance=_parse_float(
            _get(env, prefix, "BROKER_PRICE_TOLERANCE", defaults),
            var("BROKER_PRICE_TOLERANCE"),
        ),
        primary_sessions=_parse_sessions(_get(env, prefix, "PRIMARY_SESSIONS", defaults)),
        cooldown_minutes_override=_parse_optional_int(
            _get(env, prefix, "COOLDOWN_MINUTES_OVERRIDE", defaults),
            var("COOLDOWN_MINUTES_OVERRIDE"),
        ),
        atr_stop_multiplier_override=_parse_optional_float(
            _get(env, prefix, "ATR_STOP_MULTIPLIER_OVERRIDE", defaults),
            var("ATR_STOP_MULTIPLIER_OVERRIDE"),
        ),
        min_net_reward_r_override=_parse_optional_float(
            _get(env, prefix, "MIN_NET_REWARD_R_OVERRIDE", defaults),
            var("MIN_NET_REWARD_R_OVERRIDE"),
        ),
    )
    _validate_instrument_profile(profile)
    return profile


def load_all_instrument_profiles(
    env: Mapping[str, str] | None = None,
) -> dict[str, InstrumentProfile]:
    env = os.environ if env is None else env
    return {code: load_instrument_profile(code, env) for code in INSTRUMENT_CODES}


def _validate_instrument_profile(p: InstrumentProfile) -> None:
    prefix = f"GOLDSIGNAL_{p.code}_"
    if p.pip_size <= 0 or p.tick_size <= 0:
        raise ConfigError(f"{prefix}PIP_SIZE/{prefix}TICK_SIZE must be positive")
    if p.decimal_precision < 0:
        raise ConfigError(f"{prefix}DECIMAL_PRECISION must be >= 0")
    if p.contract_size is not None and p.contract_size <= 0:
        raise ConfigError(f"{prefix}CONTRACT_SIZE must be positive when set")
    if p.typical_spread < 0 or p.typical_slippage < 0 or p.transaction_cost < 0:
        raise ConfigError(
            f"{prefix}TYPICAL_SPREAD/{prefix}TYPICAL_SLIPPAGE/{prefix}TRANSACTION_COST "
            "must be >= 0"
        )
    if p.max_permitted_spread < p.typical_spread:
        raise ConfigError(f"{prefix}MAX_PERMITTED_SPREAD must be >= {prefix}TYPICAL_SPREAD")
    if p.broker_price_tolerance < 0:
        raise ConfigError(f"{prefix}BROKER_PRICE_TOLERANCE must be >= 0")
    if p.cooldown_minutes_override is not None and p.cooldown_minutes_override < 0:
        raise ConfigError(f"{prefix}COOLDOWN_MINUTES_OVERRIDE must be >= 0 when set")
    if p.atr_stop_multiplier_override is not None and p.atr_stop_multiplier_override <= 0:
        raise ConfigError(f"{prefix}ATR_STOP_MULTIPLIER_OVERRIDE must be positive when set")
    if p.min_net_reward_r_override is not None and p.min_net_reward_r_override <= 0:
        raise ConfigError(f"{prefix}MIN_NET_REWARD_R_OVERRIDE must be positive when set")


def effective_mode_config(base: ModeConfig, profile: InstrumentProfile) -> ModeConfig:
    """Overlay `profile`'s cost fields (and any explicit overrides) onto
    `base` — every other `ModeConfig` field is untouched. For XAU/USD's
    default profile this reproduces `base` byte-for-byte (see
    `tests/test_instruments.py`), so wiring this in later can never change
    today's existing gold behavior.
    """
    return dataclasses.replace(
        base,
        estimated_spread=profile.typical_spread,
        estimated_slippage=profile.typical_slippage,
        estimated_transaction_cost=profile.transaction_cost,
        cooldown_minutes=(
            profile.cooldown_minutes_override
            if profile.cooldown_minutes_override is not None
            else base.cooldown_minutes
        ),
        atr_stop_multiplier=(
            profile.atr_stop_multiplier_override
            if profile.atr_stop_multiplier_override is not None
            else base.atr_stop_multiplier
        ),
        min_net_reward_r=(
            profile.min_net_reward_r_override
            if profile.min_net_reward_r_override is not None
            else base.min_net_reward_r
        ),
    )
