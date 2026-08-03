"""Policy-plan schema: explainable action records over seiba findings."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from seiba_risk_scanner.classification_engine.pipeline_models import Origin

PolicyActionSource = Literal[
    "openmed_action_for",
    "openmed_policy_label_actions",
    "neutral_keep",
    "seiba_action_override",
]


class ActionRecord(BaseModel):
    """One finding's planned (and optionally executed) de-identification action."""

    model_config = {"extra": "forbid"}

    entity_id: str
    entity: str
    text: str
    start: int
    end: int
    openmed_label: Optional[str] = None
    seiba_data_class: Optional[str] = None
    openmed_policy_class: Optional[str] = None
    policy_name: str
    action: str = Field(
        description="OpenMed action vocabulary: keep|redact|mask|replace|hash|format_preserve, "
        "plus the Seiba-owned 'generalize'"
    )
    generalization_level: Optional[str] = Field(
        default=None,
        description="Rung applied when action='generalize' (e.g. 'year', '5_year_band')",
    )
    source: PolicyActionSource
    detail: str
    execute_fallback: Optional[str] = Field(
        default=None,
        description="When execute downgraded the action, e.g. 'replace→mask'",
    )
    replacement: Optional[str] = Field(
        default=None,
        description="Ephemeral scrubbed value when execute ran; not a vault entry",
    )
    provenance: Optional[dict] = None
    origin: Optional[Origin] = Field(
        default=None, description="Which input this span came from; carried from the detection"
    )

    @property
    def field_name(self) -> str:
        """The column/key this finding came from, else the entity name."""
        if self.origin and self.origin.column:
            return self.origin.column
        provenance = self.provenance or {}
        return provenance.get("column") or provenance.get("key") or self.entity

    @property
    def scrubbed_value(self) -> str:
        """The value after scrub; the original when execute never ran."""
        return self.text if self.replacement is None else self.replacement


class PolicyPlanSection(BaseModel):
    """Aggregated policy plan attached to a readiness/exposure report."""

    model_config = {"extra": "forbid"}

    policy_name: str
    records: List[ActionRecord] = Field(default_factory=list)
    action_histogram: Dict[str, int] = Field(default_factory=dict)
    exact_count: int = 0
    class_fallback_count: int = 0
    neutral_keep_count: int = 0
    executed: bool = False


__all__ = [
    "ActionRecord",
    "PolicyActionSource",
    "PolicyPlanSection",
]
