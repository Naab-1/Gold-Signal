"""Trade-management presets and breakeven rules.

These are NOT claimed to be optimal — they are configurable partial-close
schemes that Phase 2's backtester simulates and reports on independently,
so a preset is chosen from evidence, not assumed to be best.

Phase 1 only defines and validates these types; the backtester (Phase 2)
and paper-trading journal (Phase 3) are what actually apply them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TradeManagementPreset(str, Enum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    RUNNER = "runner"


# (TP1 %, TP2 %, TP3 %) of position closed at each target, when all three exist.
PRESET_ALLOCATIONS: dict[TradeManagementPreset, tuple[float, float, float]] = {
    TradeManagementPreset.CONSERVATIVE: (0.5, 0.3, 0.2),
    TradeManagementPreset.BALANCED: (0.3, 0.4, 0.3),
    TradeManagementPreset.RUNNER: (0.2, 0.3, 0.5),
}


class TpShortfallHandling(str, Enum):
    """How to distribute a preset's allocation when fewer than 3 targets exist."""

    NORMALIZE = "normalize"  # scale remaining allocations proportionally to sum to 100%
    LAST_TARGET_ABSORBS = "last_target_absorbs"  # the last available target takes the rest


def resolve_allocations(
    preset: TradeManagementPreset,
    num_targets: int,
    shortfall_mode: TpShortfallHandling,
) -> list[float]:
    """Fraction of the position to close at each existing target, summing to 1.0."""
    if not 1 <= num_targets <= 3:
        raise ValueError("num_targets must be 1, 2, or 3")

    full = PRESET_ALLOCATIONS[preset]
    if num_targets == 3:
        return list(full)

    used = list(full[:num_targets])
    if shortfall_mode == TpShortfallHandling.NORMALIZE:
        total = sum(used)
        return [u / total for u in used]

    remainder = sum(full[num_targets:])
    used[-1] += remainder
    return used


class BreakevenTrigger(str, Enum):
    NONE = "none"
    AFTER_TP1_CONFIRMED = "after_tp1_confirmed"
    AFTER_R_MULTIPLE = "after_r_multiple"


@dataclass(frozen=True)
class BreakevenRule:
    """Stop-to-breakeven behavior. Defaults to NONE: a stop is never moved to
    breakeven automatically just because TP1 was touched, per the user's
    explicit requirement — this must be deliberately configured.
    """

    trigger: BreakevenTrigger = BreakevenTrigger.NONE
    after_r_multiple: float | None = None

    def __post_init__(self) -> None:
        if self.trigger == BreakevenTrigger.AFTER_R_MULTIPLE:
            if self.after_r_multiple is None or self.after_r_multiple <= 0:
                raise ValueError(
                    "AFTER_R_MULTIPLE breakeven trigger requires a positive after_r_multiple"
                )
        elif self.after_r_multiple is not None:
            raise ValueError("after_r_multiple only applies to the AFTER_R_MULTIPLE trigger")
