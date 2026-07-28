"""Utility-loss measurement: how much analytic value the scrub destroyed.

Each finding's loss is scored from three checkable properties of its real (original -> scrubbed)
pair — recoverability, distinguishability, shape — combined with tunable per-property weights.
Only the weights are a judgement call; the properties themselves are measured from the output.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from pydantic import BaseModel, Field

from seiba_risk_scanner.policy.models import ActionRecord


@dataclass(frozen=True)
class UtilityWeights:
    """What each preserved property is worth analytically. Loss is normalized by their sum."""

    recoverable: float = 0.2
    distinguishable: float = 0.5
    shaped: float = 0.3


DEFAULT_UTILITY_WEIGHTS = UtilityWeights()


class UtilityLoss(BaseModel):
    """Analytic utility destroyed by the scrub; 0 = nothing lost, 1 = everything lost."""

    model_config = {"extra": "forbid"}

    overall: float = Field(ge=0.0, le=1.0)
    by_data_class: Dict[str, float] = Field(default_factory=dict)
    per_finding_loss: List[float] = Field(
        default_factory=list, description="Loss per action record, in plan order"
    )
    finding_count: int = 0


def _shape(value: str) -> str:
    """Char-class signature: digits -> D, letters -> A, everything else kept verbatim."""
    return "".join("D" if c.isdigit() else "A" if c.isalpha() else c for c in value)


def _distinguishability(records: Sequence[ActionRecord]) -> Dict[str, float]:
    """Share of a field's distinct originals that survive as distinct scrubbed values.

    Graded rather than yes/no, because partial collapse is the whole point of generalization:
    masking drives a column to one token (~0), coarsening a zip to three digits still keeps
    regions apart (partial), hashing keeps every value apart (1.0). A boolean here scored
    generalization identically to masking and hid the difference the action exists to make.
    """
    mapping: Dict[str, Dict[str, str]] = defaultdict(dict)
    for record in records:
        mapping[record.field_name][record.text] = record.scrubbed_value
    return {
        field: (len(set(pairs.values())) / len(pairs) if pairs else 1.0)
        for field, pairs in mapping.items()
    }


def utility_loss(
    records: Sequence[ActionRecord],
    weights: UtilityWeights = DEFAULT_UTILITY_WEIGHTS,
) -> Optional[UtilityLoss]:
    """Measure analytic utility lost across an executed plan; ``per_record_loss`` mirrors input.

    Returns None when there is nothing to score.
    """
    if not records:
        return None

    distinguishable = _distinguishability(records)
    denom = weights.recoverable + weights.distinguishable + weights.shaped

    per_finding: List[float] = []
    class_sum: Dict[str, float] = defaultdict(float)
    class_count: Dict[str, int] = defaultdict(int)
    for record in records:
        scrubbed = record.scrubbed_value
        lost = 0.0
        if scrubbed != record.text:                      # exact value no longer recoverable
            lost += weights.recoverable
        # Graded: the share of distinct values this field's action collapsed away.
        lost += weights.distinguishable * (1.0 - distinguishable[record.field_name])
        if _shape(scrubbed) != _shape(record.text):      # format / type destroyed
            lost += weights.shaped
        loss = lost / denom if denom else 0.0
        per_finding.append(loss)
        cls = record.seiba_data_class or "unknown"
        class_sum[cls] += loss
        class_count[cls] += 1

    return UtilityLoss(
        overall=sum(per_finding) / len(per_finding),
        by_data_class={c: class_sum[c] / class_count[c] for c in class_sum},
        per_finding_loss=per_finding,
        finding_count=len(per_finding),
    )


__all__ = ["UtilityWeights", "DEFAULT_UTILITY_WEIGHTS", "UtilityLoss", "utility_loss"]
