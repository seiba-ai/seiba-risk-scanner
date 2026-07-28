"""Residual re-identification measurement over an executed policy plan (openmed.risk).

Given the original values and their scrubbed replacements (one record per group of executed
:class:`ActionRecord`), wrap ``openmed.risk.risk_report`` to score how much residual risk the
scrub left. Assessor-free and self-contained so both the report path and a future optimizer
can call it as a scoring oracle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from seiba_risk_scanner.policy.generalize import precision_factor
from seiba_risk_scanner.policy.models import ActionRecord

# Classes whose raw value surviving is an outright failure of the scrub.
_LEAKY_CLASSES = frozenset({"direct_identifier", "financial_data", "biometric_identifier"})


@dataclass(frozen=True)
class ResidualRisk:
    """Residual risk of a scrubbed corpus versus its original."""

    reid_rate: float
    leakage_rate: float
    residual_k: int
    record_count: int


def _record_pair(group: Sequence[ActionRecord]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build (original, scrubbed) field-map dicts for one record from its executed actions.

    Direct identifiers stay in the record, unlike the k-anonymity grouping: leakage is measured
    precisely on whether a direct value survived. A shared column keeps its last action's value.
    """
    original: Dict[str, Any] = {}
    scrubbed: Dict[str, Any] = {}
    for record in group:
        original[record.field_name] = record.text
        scrubbed[record.field_name] = record.scrubbed_value
    return original, scrubbed


def _leaked(group: Sequence[ActionRecord]) -> bool:
    """True when a direct identifier came through the scrub unchanged.

    Measured here rather than taken from OpenMed: its leakage check treats any value that is
    not an ALL-CAPS token as a survivor, so a hash (``EMAIL_2f9c…``) or a generalized date
    (``1989``) counts as leaked even though the original is gone. We hold both sides of the
    pair, so "did this exact value survive" is an equality test, not a heuristic.
    """
    return any(
        record.seiba_data_class in _LEAKY_CLASSES and record.scrubbed_value == record.text
        for record in group
    )


def residual_risk(groups: Sequence[Sequence[ActionRecord]]) -> Optional[ResidualRisk]:
    """Measure residual reid/leakage of a self-scrubbed corpus, one record per group.

    Each group holds the executed ActionRecords (``replacement`` filled) for one record.
    Returns None when there is nothing to compare.
    """
    populated = [group for group in groups if group]
    pairs = [_record_pair(group) for group in populated]
    if not pairs:
        return None

    from openmed.risk import risk_report  # heavy import, only needed here

    report = risk_report(
        deidentified=[scrubbed for _, scrubbed in pairs],
        original=[original for original, _ in pairs],
    )
    return ResidualRisk(
        reid_rate=report["reid_rate"],
        leakage_rate=sum(_leaked(group) for group in populated) / len(populated),
        residual_k=report["k_min"],
        record_count=len(pairs),
    )


# How much of a finding's severity survives its action. A masked value is simply gone; a
# surrogate or hash hides the person but still lets records be linked, so a little risk
# remains; a generalized value keeps whatever its precision keeps.
ACTION_SEVERITY_RETENTION = {
    "keep": 1.0,
    "hash": 0.15,
    "format_preserve": 0.10,
    "replace": 0.10,
    "mask": 0.0,
    "redact": 0.0,
}


def residual_score(score: float, record: ActionRecord) -> float:
    """Re-score one finding against what the scrub actually left behind."""
    if record.action == "generalize":
        factor, _ = precision_factor(record.scrubbed_value, record.openmed_label)
        return score * factor
    return score * ACTION_SEVERITY_RETENTION.get(record.action, 0.0)


__all__ = [
    "ACTION_SEVERITY_RETENTION",
    "ResidualRisk",
    "residual_risk",
    "residual_score",
]
