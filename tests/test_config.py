import pytest

from goldsignal.config import (
    ConfigError,
    load_daytrade_config,
    load_global_settings,
    load_scalp_config,
)
from goldsignal.models.candle import Timeframe


def test_global_defaults():
    s = load_global_settings({})
    assert s.data_provider == "mock"
    assert s.instrument == "XAUUSD"
    assert s.log_level == "INFO"
    assert s.twelvedata_api_key is None
    assert s.telegram_bot_token is None
    assert s.telegram_debug_mode is False
    assert s.database_url is None


def test_global_requires_twelvedata_key_when_selected():
    with pytest.raises(ConfigError):
        load_global_settings({"GOLDSIGNAL_DATA_PROVIDER": "twelvedata"})


def test_global_accepts_twelvedata_with_key():
    s = load_global_settings(
        {"GOLDSIGNAL_DATA_PROVIDER": "twelvedata", "GOLDSIGNAL_TWELVEDATA_API_KEY": "abc123"}
    )
    assert s.twelvedata_api_key == "abc123"


def test_global_rejects_empty_instrument():
    with pytest.raises(ConfigError):
        load_global_settings({"GOLDSIGNAL_INSTRUMENT": "  "})


def test_global_rejects_bad_log_level():
    with pytest.raises(ConfigError):
        load_global_settings({"GOLDSIGNAL_LOG_LEVEL": "LOUD"})


def test_scalp_defaults_use_5m_15m():
    c = load_scalp_config({})
    assert c.entry_timeframe == Timeframe.M5
    assert c.confirmation_timeframe == Timeframe.M15
    assert c.enabled is True


def test_daytrade_defaults_use_15m_1h():
    c = load_daytrade_config({})
    assert c.entry_timeframe == Timeframe.M15
    assert c.confirmation_timeframe == Timeframe.H1


def test_modes_are_independently_configurable():
    scalp = load_scalp_config({"GOLDSIGNAL_SCALP_ATR_STOP_MULTIPLIER": "9.0"})
    daytrade = load_daytrade_config({})
    assert scalp.atr_stop_multiplier == 9.0
    assert daytrade.atr_stop_multiplier != 9.0


def test_confirmation_timeframe_must_be_longer_than_entry():
    with pytest.raises(ConfigError):
        load_scalp_config({"GOLDSIGNAL_SCALP_CONFIRMATION_TIMEFRAME": "M5"})


def test_ema_fast_must_be_less_than_slow():
    with pytest.raises(ConfigError):
        load_scalp_config({"GOLDSIGNAL_SCALP_EMA_FAST_PERIOD": "60"})


def test_invalid_trade_management_preset_rejected():
    with pytest.raises(ConfigError):
        load_scalp_config({"GOLDSIGNAL_SCALP_TRADE_MANAGEMENT_PRESET": "aggressive"})


def test_breakeven_after_r_multiple_required_when_trigger_is_after_r_multiple():
    with pytest.raises(ValueError):
        load_scalp_config({"GOLDSIGNAL_SCALP_BREAKEVEN_TRIGGER": "after_r_multiple"})


def test_breakeven_after_r_multiple_parsed_when_present():
    c = load_scalp_config(
        {
            "GOLDSIGNAL_SCALP_BREAKEVEN_TRIGGER": "after_r_multiple",
            "GOLDSIGNAL_SCALP_BREAKEVEN_AFTER_R_MULTIPLE": "1.5",
        }
    )
    assert c.breakeven_after_r_multiple == 1.5


def test_non_numeric_period_raises_config_error():
    with pytest.raises(ConfigError):
        load_scalp_config({"GOLDSIGNAL_SCALP_EMA_FAST_PERIOD": "not-a-number"})
