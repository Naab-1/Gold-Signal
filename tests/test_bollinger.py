import pytest

from goldsignal.indicators.bollinger import bollinger_band_width, bollinger_bands


def test_bollinger_rejects_non_positive_period():
    with pytest.raises(ValueError):
        bollinger_bands([1.0, 2.0, 3.0], period=0)


def test_bollinger_rejects_non_positive_num_std():
    with pytest.raises(ValueError):
        bollinger_bands([1.0, 2.0, 3.0], period=2, num_std=0)


def test_bollinger_insufficient_history_returns_none():
    upper, middle, lower = bollinger_bands([1.0, 2.0], period=5)
    assert upper == [None, None]
    assert middle == [None, None]
    assert lower == [None, None]


def test_bollinger_bands_exact_values_constant_series():
    # Zero standard deviation for a flat series -- bands collapse to the mean.
    closes = [10.0, 10.0, 10.0, 10.0]
    upper, middle, lower = bollinger_bands(closes, period=3, num_std=2.0)
    assert middle[2] == pytest.approx(10.0)
    assert upper[2] == pytest.approx(10.0)
    assert lower[2] == pytest.approx(10.0)


def test_bollinger_bands_exact_values_hand_computed():
    # window = [8, 10, 12] -> mean=10
    # population std = sqrt(((8-10)^2+(10-10)^2+(12-10)^2)/3) = sqrt(8/3)
    closes = [8.0, 10.0, 12.0]
    upper, middle, lower = bollinger_bands(closes, period=3, num_std=1.0)
    std = (8.0 / 3) ** 0.5
    assert middle[2] == pytest.approx(10.0)
    assert upper[2] == pytest.approx(10.0 + std)
    assert lower[2] == pytest.approx(10.0 - std)


def test_bollinger_band_width_wider_for_more_volatile_series():
    stable = [100.0, 100.2, 99.8, 100.1, 99.9, 100.0, 100.1, 99.9, 100.0, 100.1] * 3
    volatile = [100.0, 105.0, 95.0, 108.0, 92.0, 103.0, 97.0, 106.0, 94.0, 101.0] * 3
    width_stable = bollinger_band_width(stable, period=10)[-1]
    width_volatile = bollinger_band_width(volatile, period=10)[-1]
    assert width_stable is not None
    assert width_volatile is not None
    assert width_volatile > width_stable
