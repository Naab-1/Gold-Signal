"""Shared stop-loss placement: ATR-buffer widened by structure when the
structural reference is more conservative. Extracted from the original
A+ rule (`strategy/_common.py`) so the new A-tier continuation rule
(`strategy/classification.py`) reuses the exact same, already-verified
logic rather than a second copy of it.
"""

from __future__ import annotations

from goldsignal.models.signal import SignalDirection


def compute_stop_loss(
    *,
    direction: SignalDirection,
    entry_price: float,
    atr: float,
    atr_stop_multiplier: float,
    structural_ref: float | None,
    tolerance: float,
) -> float:
    atr_stop = (
        entry_price - atr_stop_multiplier * atr
        if direction == SignalDirection.BUY
        else entry_price + atr_stop_multiplier * atr
    )
    if direction == SignalDirection.BUY:
        candidates = [atr_stop]
        if structural_ref is not None:
            candidates.append(structural_ref - tolerance)
        return min(candidates)
    else:
        candidates = [atr_stop]
        if structural_ref is not None:
            candidates.append(structural_ref + tolerance)
        return max(candidates)
