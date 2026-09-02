import argparse

import pytest

from goldsignal.analysis.cli import _parse_broker_price_arg


def test_valid_broker_price_arg():
    assert _parse_broker_price_arg("EURUSD=1.0850") == ("EURUSD", 1.0850)


def test_lowercase_code_is_normalized_uppercase():
    assert _parse_broker_price_arg("eurusd=1.0850") == ("EURUSD", 1.0850)


def test_missing_equals_sign_raises():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_broker_price_arg("EURUSD1.0850")


def test_unknown_instrument_code_raises():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_broker_price_arg("BTCUSD=50000")


def test_non_numeric_price_raises():
    with pytest.raises(argparse.ArgumentTypeError):
        _parse_broker_price_arg("EURUSD=not-a-number")
