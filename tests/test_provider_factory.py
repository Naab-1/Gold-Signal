import pytest

from goldsignal.config import ConfigError, load_global_settings
from goldsignal.data.mock_provider import MockDataProvider
from goldsignal.data.provider import get_data_provider
from goldsignal.data.twelvedata_provider import TwelveDataProvider


def test_factory_returns_mock_provider_by_default():
    settings = load_global_settings({})
    provider = get_data_provider(settings)
    assert isinstance(provider, MockDataProvider)


def test_factory_returns_twelvedata_provider_when_selected():
    settings = load_global_settings(
        {"GOLDSIGNAL_DATA_PROVIDER": "twelvedata", "GOLDSIGNAL_TWELVEDATA_API_KEY": "abc123"}
    )
    provider = get_data_provider(settings)
    assert isinstance(provider, TwelveDataProvider)


def test_factory_rejects_unknown_provider():
    settings = load_global_settings({"GOLDSIGNAL_DATA_PROVIDER": "unknown_vendor"})
    with pytest.raises(ConfigError):
        get_data_provider(settings)


def test_verify_consistency_defaults_true_and_can_be_disabled():
    settings = load_global_settings(
        {"GOLDSIGNAL_DATA_PROVIDER": "twelvedata", "GOLDSIGNAL_TWELVEDATA_API_KEY": "abc123"}
    )
    assert get_data_provider(settings)._verify_consistency_enabled is True
    assert (
        get_data_provider(settings, verify_consistency=False)._verify_consistency_enabled is False
    )
