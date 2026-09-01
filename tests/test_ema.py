from goldsignal.indicators.ema import ema


def test_ema_none_before_seed():
    values = [1, 2, 3, 4, 5]
    result = ema(values, period=3)
    assert result[0] is None
    assert result[1] is None


def test_ema_seed_is_simple_average():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    result = ema(values, period=3)
    assert result[2] == 2.0  # avg(1,2,3)


def test_ema_recursive_values_linear_ramp():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    result = ema(values, period=3)
    # k = 2/(3+1) = 0.5; hand-computed from seed 2.0 at index 2
    expected_tail = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
    assert result[3:] == expected_tail


def test_ema_insufficient_data_returns_all_none():
    result = ema([1, 2], period=5)
    assert result == [None, None]


def test_ema_rejects_non_positive_period():
    import pytest

    with pytest.raises(ValueError):
        ema([1, 2, 3], period=0)
