from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from seiba_risk_scanner.classification_engine.deterministic_detectors.deterministic_detector import (
    DeterministicDetectionRow,
)


class ContextualFusionInput(BaseModel):
    """Contextual scores + optional rescue metadata for a deterministic row."""

    model_config = {"extra": "forbid"}

    confidence_contextual: float
    fused_confidence: float
    contextual_matches: Optional[List[str]] = None
    contextual_matches_before: Optional[List[str]] = None
    contextual_matches_after: Optional[List[str]] = None
    candidates: Optional[List["ContextCandidate"]] = None
    rescue_applied: bool = False
    original_entity_id: Optional[str] = None
    original_entity: Optional[str] = None
    original_ontology: Optional[str] = None


class CombinedDetectionRow(BaseModel):
    """Deterministic span with contextual stage scores and fused confidence."""

    model_config = {"extra": "forbid"}

    winner_kind: Optional[Literal["deterministic", "ner", "context_candidate", "llm"]] = Field(
        default=None,
        description="Which hypothesis kind won after contextual fusion for this span.",
    )
    entity_id: str = Field(description="Stable id: {ontology_stem}::{entity_name}")
    entity: str = Field(description="Entity key from ontology YAML")
    start: int
    end: int
    text: str
    confidence: float = Field(description="Fused score used for thresholding")
    confidence_deterministic: float
    confidence_contextual: float
    confidence_ner: Optional[float] = Field(
        default=None,
        description="NER prior used in fusion when applicable (ontology default if model has no logits)",
    )
    confidence_llm: Optional[float] = Field(
        default=None,
        description="Raw LLM-reported confidence when the span was found by the LLM gap-fill stage.",
    )
    contextual_matches: Optional[List[str]] = None
    contextual_matches_before: Optional[List[str]] = None
    contextual_matches_after: Optional[List[str]] = None
    candidates: Optional[List["ContextCandidate"]] = None
    rescue_applied: bool = False
    original_entity_id: Optional[str] = None
    original_entity: Optional[str] = None
    original_ontology: Optional[str] = None
    ontology: Optional[str] = None
    ner_label: Optional[str] = Field(
        default=None,
        description="Original spaCy/MedspaCy label when the winning hypothesis came from NER",
    )
    detected_subtype: Optional[str] = Field(
        default=None,
        description=(
            "The more specific entity_id this span was detected as, before being rolled up "
            "to its is_a parent (e.g. physician_names under a person_names report). Kept so "
            "severity and audit can use the finer distinction; None when no rollup occurred."
        ),
    )
    stage: Literal["deterministic+ner+contextual", "deterministic+contextual"] = (
        "deterministic+ner+contextual"
    )
    provenance: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional source (e.g. dataframe row/column) for structured inputs",
    )

    @classmethod
    def from_deterministic(
        cls,
        row: DeterministicDetectionRow,
        fusion: ContextualFusionInput,
    ) -> "CombinedDetectionRow":
        return cls(
            winner_kind="deterministic",
            entity_id=row.entity_id,
            entity=row.entity,
            start=row.start,
            end=row.end,
            text=row.text,
            confidence=fusion.fused_confidence,
            confidence_deterministic=row.confidence,
            confidence_contextual=fusion.confidence_contextual,
            contextual_matches=fusion.contextual_matches,
            contextual_matches_before=fusion.contextual_matches_before,
            contextual_matches_after=fusion.contextual_matches_after,
            candidates=fusion.candidates,
            rescue_applied=fusion.rescue_applied,
            original_entity_id=fusion.original_entity_id,
            original_entity=fusion.original_entity,
            original_ontology=fusion.original_ontology,
            ontology=row.ontology,
            provenance=row.provenance,
            confidence_ner=None,
            ner_label=None,
            stage="deterministic+ner+contextual",
        )


class ContextCandidate(BaseModel):
    """Alternative entity suggested by contextual phrases near the same span."""

    model_config = {"extra": "forbid"}

    entity_id: str
    entity: str
    confidence_contextual: float
    matched_phrases: List[str] = Field(default_factory=list)
    matched_in_before: List[str] = Field(default_factory=list)
    matched_in_after: List[str] = Field(default_factory=list)


class PipelineStageResult(BaseModel):
    """Deterministic detection plus contextual phrase scoring and fusion."""

    model_config = {"extra": "forbid"}

    stage: Literal["deterministic+ner+contextual", "deterministic+contextual"] = (
        "deterministic+ner+contextual"
    )
    detections: List[CombinedDetectionRow] = Field(default_factory=list)
    text_length: int = 0
    fusion_weight_deterministic: float = 0.65
    fusion_weight_contextual: float = 0.35


__all__ = ["CombinedDetectionRow", "ContextCandidate", "ContextualFusionInput", "PipelineStageResult"]
