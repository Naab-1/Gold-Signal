"""Mechanically enforces the STRATEGY RESEARCH AND REPLACEMENT program's
Phase 3 rule, in the spec's own words: "After the final out-of-sample test,
do not adjust the strategy and report the same final test as independent
evidence. Any adjustment creates a new strategy version requiring new
unseen data."

Built now, before any candidate strategy exists (Phase 4 hasn't started),
following this project's own established pattern of building a guardrail
*before* a good strategy exists rather than trusting future-session
discipline (see `ModeConfig.actionable_alerts_enabled`, Phase 1). A
file-based JSON-lines ledger, not Postgres: this is a research-time audit
trail, not live production state (contrast `persistence/`, which is
entirely psycopg-backed live state).

`ledger_path` has no default anywhere in this module -- matching
`persistence/db.py::connect(database_url)`'s "must be explicit, no silent
fallback" convention for anything guarding a real safety rule.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from goldsignal.backtest.export import to_jsonable
from goldsignal.backtest.models import BacktestSummary


class FinalOosAlreadyEvaluatedError(RuntimeError):
    """Raised when the same (strategy_version, instrument, mode) is about
    to be evaluated against final-out-of-sample data a second time -- the
    spec's rule is that any adjustment must produce a new strategy
    version (and therefore a new unseen dataset), not a repeat look at
    data already used to judge this exact version.
    """


@dataclass(frozen=True)
class FinalOosEvaluation:
    strategy_version: str
    instrument: str
    mode: str
    evaluated_at: datetime
    summary: BacktestSummary
    # Audit context only (e.g. "180d, TwelveData, fetched 2026-09-05") --
    # deliberately NOT part of the guard key, so a deeper future history
    # pull for the same instrument doesn't retroactively change blocking
    # behavior; it's just a breadcrumb for a future session reasoning
    # about what data a past evaluation actually used.
    dataset_note: str = ""


def _key(*, strategy_version: str, instrument: str, mode: str) -> tuple[str, str, str]:
    return (strategy_version, instrument, mode)


def _read_entries(ledger_path: Path) -> list[dict]:
    if not ledger_path.exists():
        return []
    entries = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def has_been_evaluated(
    ledger_path: Path, *, strategy_version: str, instrument: str, mode: str
) -> bool:
    target = _key(strategy_version=strategy_version, instrument=instrument, mode=mode)
    for entry in _read_entries(ledger_path):
        if _key(**{k: entry[k] for k in ("strategy_version", "instrument", "mode")}) == target:
            return True
    return False


def record_evaluation(ledger_path: Path, evaluation: FinalOosEvaluation) -> None:
    """Append-only -- never overwrites or removes a prior entry."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(to_jsonable(evaluation))
    with ledger_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def assert_not_yet_evaluated(
    ledger_path: Path, *, strategy_version: str, instrument: str, mode: str
) -> None:
    """Call this immediately before running any final-out-of-sample
    evaluation in Phase 4+. Raises `FinalOosAlreadyEvaluatedError` if
    `has_been_evaluated` is True for this exact (strategy_version,
    instrument, mode).
    """
    if has_been_evaluated(
        ledger_path, strategy_version=strategy_version, instrument=instrument, mode=mode
    ):
        raise FinalOosAlreadyEvaluatedError(
            f"strategy_version={strategy_version!r} instrument={instrument!r} mode={mode!r} "
            "has already been evaluated against final-out-of-sample data. Any adjustment "
            "must produce a new strategy_version and be evaluated on new unseen data -- "
            "re-testing the same version here would not be independent evidence."
        )
