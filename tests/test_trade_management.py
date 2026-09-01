import pytest

from goldsignal.strategy.trade_management import (
    PRESET_ALLOCATIONS,
    BreakevenRule,
    BreakevenTrigger,
    TpShortfallHandling,
    TradeManagementPreset,
    resolve_allocations,
)


@pytest.mark.parametrize("preset", list(TradeManagementPreset))
def test_full_allocation_sums_to_one(preset):
    assert sum(PRESET_ALLOCATIONS[preset]) == pytest.approx(1.0)


def test_resolve_allocations_three_targets_returns_full_preset():
    result = resolve_allocations(TradeManagementPreset.BALANCED, 3, TpShortfallHandling.NORMALIZE)
    assert result == list(PRESET_ALLOCATIONS[TradeManagementPreset.BALANCED])


def test_resolve_allocations_normalize_sums_to_one():
    result = resolve_allocations(
        TradeManagementPreset.CONSERVATIVE, 2, TpShortfallHandling.NORMALIZE
    )
    assert sum(result) == pytest.approx(1.0)
    # 0.5:0.3 ratio preserved
    assert result[0] == pytest.approx(0.5 / 0.8)


def test_resolve_allocations_last_target_absorbs():
    result = resolve_allocations(
        TradeManagementPreset.RUNNER, 1, TpShortfallHandling.LAST_TARGET_ABSORBS
    )
    assert result == [pytest.approx(1.0)]


def test_resolve_allocations_rejects_bad_target_count():
    with pytest.raises(ValueError):
        resolve_allocations(TradeManagementPreset.BALANCED, 0, TpShortfallHandling.NORMALIZE)
    with pytest.raises(ValueError):
        resolve_allocations(TradeManagementPreset.BALANCED, 4, TpShortfallHandling.NORMALIZE)


def test_breakeven_rule_defaults_to_none_trigger():
    rule = BreakevenRule()
    assert rule.trigger == BreakevenTrigger.NONE
    assert rule.after_r_multiple is None


def test_breakeven_rule_requires_r_multiple_when_after_r_multiple():
    with pytest.raises(ValueError):
        BreakevenRule(trigger=BreakevenTrigger.AFTER_R_MULTIPLE)


def test_breakeven_rule_rejects_r_multiple_on_other_triggers():
    with pytest.raises(ValueError):
        BreakevenRule(trigger=BreakevenTrigger.NONE, after_r_multiple=1.0)
