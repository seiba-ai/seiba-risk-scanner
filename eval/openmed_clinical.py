"""OpenMed clinical (disease) eval helpers."""

from __future__ import annotations

from typing import FrozenSet

# Default clinical model: BigMed 560M (accessible PyTorch DiseaseDetect on HF).
# Smaller TinyMed PyTorch repos were removed; -mlx variants need MLX, not the SDK torch path.
OPENMED_CLINICAL_ENTITY_IDS: FrozenSet[str] = frozenset(
    {
        "openmed::DISEASE",
        "openmed::CONDITION",
        "openmed::PATHOLOGY",
    }
)

DEFAULT_CLINICAL_MODEL = "OpenMed/OpenMed-NER-DiseaseDetect-BigMed-560M"
DEFAULT_CLINICAL_LABEL_SET = "OpenMed/OpenMed-NER-DiseaseDetect-BigMed-560M"


def is_clinical_entity_id(entity_id: str) -> bool:
    return entity_id in OPENMED_CLINICAL_ENTITY_IDS


def is_pii_entity_id(entity_id: str) -> bool:
    return entity_id.startswith("openmed::") and not is_clinical_entity_id(entity_id)
