import pytest

from goldsignal.indicators.rsi import rsi


def test_rsi_none_before_seed():
    closes = [10.0] * 10
    result = rsi(closes, period=14)
    assert result == [None] * 10


def test_rsi_all_gains_is_100():
    closes = [10.0 + i for i in range(20)]
    result = rsi(closes, period=14)
    for v in result[14:]:
        assert v == 100.0


def test_rsi_all_losses_is_0():
    closes = [30.0 - i for i in range(20)]
    result = rsi(closes, period=14)
    for v in result[14:]:
        assert v == 0.0


def test_rsi_bounded_between_0_and_100():
    import random

    rng = random.Random(1)
    closes = [100.0]
    for _ in range(50):
        closes.append(closes[-1] + rng.uniform(-3, 3))
    result = rsi(closes, period=14)
    for v in result:
        if v is not None:
            assert 0.0 <= v <= 100.0


def test_rsi_rejects_non_positive_period():
    with pytest.raises(ValueError):
        rsi([1.0, 2.0], period=0)
