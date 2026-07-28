"""Seiba ontology ↔ OpenMed policy bridges (exact label + data_class fallback)."""

from __future__ import annotations

from typing import Mapping, Optional

from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    DataClass,
    EntityConfig,
)

# OpenMed PolicyProfile.policy_label_actions keys (NOT passed to action_for).
DIRECT_IDENTIFIER = "DIRECT_IDENTIFIER"
QUASI_IDENTIFIER = "QUASI_IDENTIFIER"
CLINICAL_CONCEPT = "CLINICAL_CONCEPT"

# Seiba data_class → OpenMed policy class. Genetic maps to DIRECT (not CLINICAL):
# OpenMed gene/variant labels are CLINICAL and many profiles keep those under GDPR.
DATA_CLASS_TO_POLICY_CLASS: Mapping[DataClass, str] = {
    DataClass.DIRECT_IDENTIFIER: DIRECT_IDENTIFIER,
    DataClass.FINANCIAL_DATA: DIRECT_IDENTIFIER,
    DataClass.BIOMETRIC_IDENTIFIER: DIRECT_IDENTIFIER,
    DataClass.DEVICE_IDENTIFIER: DIRECT_IDENTIFIER,
    DataClass.GENETIC_DATA: DIRECT_IDENTIFIER,
    DataClass.QUASI_IDENTIFIER: QUASI_IDENTIFIER,
    DataClass.SENSITIVE_ATTRIBUTE: QUASI_IDENTIFIER,
    # neutral intentionally absent → keep
}


def canonical_label_for(
    entity_id: str,
    configs: Mapping[str, EntityConfig],
) -> Optional[str]:
    """Return OpenMed canonical label from ontology ``de_identifier``, if set."""
    config = configs.get(entity_id)
    if config is None:
        return None
    label = config.de_identifier
    return label.strip() if isinstance(label, str) and label.strip() else None


def openmed_policy_class_for(data_class: Optional[DataClass]) -> Optional[str]:
    """Map seiba data_class to an OpenMed policy_label_actions key, or None for keep."""
    if data_class is None:
        return None
    return DATA_CLASS_TO_POLICY_CLASS.get(data_class)


def seiba_mask_token(entity_name: str) -> str:
    """Placeholder that preserves the seiba type in audits (never a fake OpenMed label)."""
    token = (entity_name or "ENTITY").strip().upper() or "ENTITY"
    return f"[{token}]"


__all__ = [
    "CLINICAL_CONCEPT",
    "DATA_CLASS_TO_POLICY_CLASS",
    "DIRECT_IDENTIFIER",
    "QUASI_IDENTIFIER",
    "canonical_label_for",
    "seiba_mask_token",
    "openmed_policy_class_for",
]
