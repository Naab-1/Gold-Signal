import dataclasses

import pytest

from goldsignal.config import ConfigError, load_daytrade_config, load_scalp_config
from goldsignal.instruments import (
    INSTRUMENT_CODES,
    effective_mode_config,
    load_all_instrument_profiles,
    load_instrument_profile,
)


def test_all_four_codes_load_with_defaults():
    profiles = load_all_instrument_profiles({})
    assert set(profiles.keys()) == set(INSTRUMENT_CODES)


def test_xauusd_defaults_reproduce_todays_existing_cost_values():
    profile = load_instrument_profile("XAUUSD", {})
    assert profile.typical_spread == 0.30
    assert profile.typical_slippage == 0.20
    assert profile.transaction_cost == 0.0
    assert profile.decimal_precision == 2


def test_eurusd_defaults_are_forex_scaled_not_gold_scaled():
    profile = load_instrument_profile("EURUSD", {})
    assert profile.decimal_precision == 5
    assert profile.typical_spread < 0.01  # nowhere near gold's $0.30
    assert profile.pip_size == 0.0001


def test_usdjpy_defaults_use_jpy_scale():
    profile = load_instrument_profile("USDJPY", {})
    assert profile.decimal_precision == 3
    assert profile.pip_size == 0.01


def test_unknown_code_raises():
    with pytest.raises(ConfigError):
        load_instrument_profile("BTCUSD", {})


def test_env_var_override():
    profile = load_instrument_profile("EURUSD", {"GOLDSIGNAL_EURUSD_TYPICAL_SPREAD": "0.0002"})
    assert profile.typical_spread == 0.0002


def test_override_fields_default_to_none():
    profile = load_instrument_profile("GBPUSD", {})
    assert profile.cooldown_minutes_override is None
    assert profile.atr_stop_multiplier_override is None
    assert profile.min_net_reward_r_override is None


def test_override_fields_can_be_set_via_env():
    profile = load_instrument_profile(
        "GBPUSD",
        {
            "GOLDSIGNAL_GBPUSD_COOLDOWN_MINUTES_OVERRIDE": "30",
            "GOLDSIGNAL_GBPUSD_ATR_STOP_MULTIPLIER_OVERRIDE": "2.5",
            "GOLDSIGNAL_GBPUSD_MIN_NET_REWARD_R_OVERRIDE": "1.8",
        },
    )
    assert profile.cooldown_minutes_override == 30
    assert profile.atr_stop_multiplier_override == 2.5
    assert profile.min_net_reward_r_override == 1.8


def test_negative_typical_spread_rejected():
    with pytest.raises(ConfigError):
        load_instrument_profile("EURUSD", {"GOLDSIGNAL_EURUSD_TYPICAL_SPREAD": "-0.0001"})


def test_max_permitted_spread_below_typical_spread_rejected():
    with pytest.raises(ConfigError):
        load_instrument_profile(
            "EURUSD",
            {
                "GOLDSIGNAL_EURUSD_TYPICAL_SPREAD": "0.0002",
                "GOLDSIGNAL_EURUSD_MAX_PERMITTED_SPREAD": "0.0001",
            },
        )


def test_non_positive_pip_size_rejected():
    with pytest.raises(ConfigError):
        load_instrument_profile("EURUSD", {"GOLDSIGNAL_EURUSD_PIP_SIZE": "0"})


def test_none_contract_size_is_accepted():
    profile = load_instrument_profile("EURUSD", {"GOLDSIGNAL_EURUSD_CONTRACT_SIZE": "none"})
    assert profile.contract_size is None


# --- effective_mode_config: the zero-regression proof for XAU/USD ---


def test_effective_mode_config_is_a_no_op_for_xauusd_scalp():
    base = load_scalp_config({})
    profile = load_instrument_profile("XAUUSD", {})
    assert effective_mode_config(base, profile) == base


def test_effective_mode_config_is_a_no_op_for_xauusd_daytrade():
    base = load_daytrade_config({})
    profile = load_instrument_profile("XAUUSD", {})
    assert effective_mode_config(base, profile) == base


def test_effective_mode_config_for_eurusd_changes_only_cost_fields():
    base = load_scalp_config({})
    profile = load_instrument_profile("EURUSD", {})
    merged = effective_mode_config(base, profile)

    assert merged.estimated_spread == profile.typical_spread
    assert merged.estimated_slippage == profile.typical_slippage
    assert merged.estimated_transaction_cost == profile.transaction_cost

    # Every other field is untouched.
    unchanged = dataclasses.replace(
        merged,
        estimated_spread=base.estimated_spread,
        estimated_slippage=base.estimated_slippage,
        estimated_transaction_cost=base.estimated_transaction_cost,
    )
    assert unchanged == base


def test_effective_mode_config_applies_explicit_overrides():
    base = load_scalp_config({})
    profile = load_instrument_profile(
        "GBPUSD",
        {
            "GOLDSIGNAL_GBPUSD_COOLDOWN_MINUTES_OVERRIDE": "99",
            "GOLDSIGNAL_GBPUSD_ATR_STOP_MULTIPLIER_OVERRIDE": "3.3",
            "GOLDSIGNAL_GBPUSD_MIN_NET_REWARD_R_OVERRIDE": "2.2",
        },
    )
    merged = effective_mode_config(base, profile)
    assert merged.cooldown_minutes == 99
    assert merged.atr_stop_multiplier == 3.3
    assert merged.min_net_reward_r == 2.2
