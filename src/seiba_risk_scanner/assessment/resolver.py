from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from seiba_risk_scanner.assessment.models import (
    Regulation,
    RuleFired,
    SeverityAssessment,
    SeverityLevel,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    DataClass,
    EntityConfig,
)
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
)
from seiba_risk_scanner.policy.generalize import precision_factor

# Severity anchor: data_class carries both harm and identifying power, so it is the only
# base input. No OpenMed policy_label multiplier — it would re-weight the same axis.
DEFAULT_BASE_SCORES: Dict[DataClass, float] = {
    DataClass.DIRECT_IDENTIFIER: 0.90,
    DataClass.GENETIC_DATA: 0.90,
    DataClass.BIOMETRIC_IDENTIFIER: 0.90,
    DataClass.FINANCIAL_DATA: 0.85,
    DataClass.SENSITIVE_ATTRIBUTE: 0.80,
    DataClass.DEVICE_IDENTIFIER: 0.60,
    DataClass.QUASI_IDENTIFIER: 0.55,
    DataClass.NEUTRAL: 0.30,
}
DEFAULT_BASE = 0.55
# CRITICAL is deliberately absent: a lone finding tops out at HIGH; only the corpus pass
# (co-occurrence / singleton records) escalates to CRITICAL.
DEFAULT_THRESHOLDS: Tuple[Tuple[SeverityLevel, float], ...] = (
    (SeverityLevel.HIGH, 0.65),
    (SeverityLevel.MEDIUM, 0.40),
    (SeverityLevel.LOW, 0.20),
)
# Above the 0.50 prior a bare NER hit carries, so an unverified name — the exact case this
# lane exists for — clears the gate instead of missing it by a hair.
REVIEW_CONFIDENCE = 0.6
REVIEW_LEVELS = frozenset({SeverityLevel.CRITICAL, SeverityLevel.HIGH})

# PCI DSS scope is payment *card* data: the PAN, the elements that travel with it, and the
# authentication values. Bank accounts, IBAN, SWIFT/BIC and crypto wallets are financial but
# are not card data, so keying PCI off data_class=financial_data over-tagged five entities.
PCI_CARD_DATA = frozenset({"credit_card_number", "cvv_code", "card_expiry_date"})


def level_for(score: float, thresholds: Sequence[Tuple[SeverityLevel, float]]) -> SeverityLevel:
    """Map a score to a level. Shared so the corpus pass can re-derive with CRITICAL added."""
    for level, minimum in thresholds:
        if score >= minimum:
            return level
    return SeverityLevel.INFO


def review_reason(
    level: SeverityLevel, confidence: float, rescued: bool, threshold: float = REVIEW_CONFIDENCE
) -> Optional[str]:
    """Route a finding to a human: severe, but we are not sure it is really there.

    Shared with the corpus pass, which re-runs it once escalation has settled the level.
    """
    if level not in REVIEW_LEVELS:
        return None
    if rescued:
        return "rescue"
    if confidence < threshold:
        return "low_confidence"
    return None


class SeverityResolver:
    """First assessment pass: scores one finding in isolation.

    severity = base(data_class), and nothing else. Confidence is deliberately *not* a factor:
    severity answers "how bad is this if exposed" (a fact about the world), while confidence
    answers "are we sure it is really here" (a fact about the scanner). Multiplying them made
    a name we were 45% sure of look like mild data, when a name is a name — the entities
    hardest to detect were the ones quietly under-reported. Confidence instead routes:
    severe-but-unsure goes to a human, severe-and-sure is actionable.
    """

    def __init__(
        self,
        *,
        base_scores: Optional[Dict[DataClass, float]] = None,
        thresholds: Optional[Sequence[Tuple[SeverityLevel, float]]] = None,
        review_confidence: float = REVIEW_CONFIDENCE,
    ) -> None:
        self.base_scores = {**DEFAULT_BASE_SCORES, **(base_scores or {})}
        self.thresholds = tuple(thresholds or DEFAULT_THRESHOLDS)
        self.review_confidence = review_confidence

    def resolve(
        self, row: CombinedDetectionRow, config: Optional[EntityConfig]
    ) -> SeverityAssessment:
        data_class = config.data_class if config else None
        base = (
            self.base_scores.get(data_class, DEFAULT_BASE)
            if data_class is not None
            else DEFAULT_BASE
        )
        name = data_class.value if data_class else "unknown"

        # Severity is the parent's, always. By design a generic parent is at least as
        # sensitive as any is_a child (a person's name outranks the physician subtype),
        # so the rollup can never lower the score. That invariant is enforced by
        # test_is_a_parent_is_at_least_as_sensitive_as_child, not papered over here — a
        # child that would outrank its parent is a modelling error, and the fix is to drop
        # the is_a link, not to let the subtype raise severity.
        confidence = max(0.0, min(1.0, row.confidence))
        # A coarse value identifies less: a bare year links against an outside roll far worse
        # than a full date of birth. This is about the value's own reach, not its uniqueness
        # here — k already owns within-dataset uniqueness, so the two do not double-count.
        factor, rung = precision_factor(row.text, config.de_identifier if config else None)
        score = base * factor

        trace = [
            RuleFired(
                rule_id=f"base:{name}",
                source="sensitivity",
                detail=f"data_class {name} -> severity {base:.2f}",
                factor=base,
            ),
            RuleFired(
                rule_id="confidence",
                source="confidence",
                detail=f"confidence {confidence:.2f} - routes review only, not part of severity",
            ),
        ]
        if rung and factor < 1.0:
            trace.append(
                RuleFired(
                    rule_id=f"precision:{rung}",
                    source="sensitivity",
                    detail=(
                        f"value is {rung.replace('_', ' ')}, not exact -> identifies less "
                        f"outside this dataset; severity {base:.2f} -> {score:.2f}"
                    ),
                    factor=factor,
                )
            )
        if row.detected_subtype:
            trace.append(
                RuleFired(
                    rule_id="subtype",
                    source="sensitivity",
                    detail=(
                        f"detected as {row.detected_subtype}, reported as parent {name}; "
                        "parent is at least as sensitive by design, so scored as parent"
                    ),
                )
            )

        tags = self._compliance_for(config)
        if tags and config is not None:
            trace.append(
                RuleFired(
                    rule_id="compliance",
                    source="compliance",
                    detail=(
                        f"category {config.classification_category} -> "
                        f"{', '.join(t.value for t in tags)}"
                    ),
                )
            )

        level = level_for(score, self.thresholds)
        reason = review_reason(level, confidence, row.rescue_applied, self.review_confidence)
        if reason:
            trace.append(
                RuleFired(
                    rule_id=f"review:{reason}",
                    source="escalation",
                    detail=f"{level.value} severity with {reason} - needs a human",
                )
            )

        return SeverityAssessment(
            level=level,
            risk_score=score,
            confidence=confidence,
            needs_review=reason is not None,
            compliance_tags=tags,
            rule_trace=trace,
        )

    @staticmethod
    def _compliance_for(config: Optional[EntityConfig]) -> List[Regulation]:
        """Map an entity to the regimes that treat it as regulated data.

        Neutral data is not personal data, so no regime applies to it — including HIPAA,
        which a category=PHI check alone would otherwise tag onto measurement units.
        """
        if config is None or config.data_class is DataClass.NEUTRAL:
            return []
        tags: List[Regulation] = []
        if config.classification_category == "PHI":
            tags.append(Regulation.HIPAA)
        if config.name in PCI_CARD_DATA:
            tags.append(Regulation.PCI)
        tags += [Regulation.GDPR, Regulation.CCPA]
        return tags


__all__ = [
    "SeverityResolver",
    "level_for",
    "review_reason",
    "DEFAULT_BASE_SCORES",
    "DEFAULT_THRESHOLDS",
]
