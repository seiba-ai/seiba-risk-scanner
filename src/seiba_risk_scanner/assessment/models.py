from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from seiba_risk_scanner.assessment.utility import UtilityLoss
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
)
from seiba_risk_scanner.policy.models import PolicyPlanSection


class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Regulation(str, Enum):
    HIPAA = "HIPAA"
    GDPR = "GDPR"
    CCPA = "CCPA"
    PCI = "PCI"


class RuleFired(BaseModel):
    """One explainability step: a rule that shaped the score, tag, or review flag."""

    model_config = {"extra": "forbid"}

    rule_id: str
    source: Literal["sensitivity", "confidence", "escalation", "compliance", "reid", "cooccurrence"]
    detail: str
    factor: Optional[float] = Field(
        default=None,
        description="Base seed (source='sensitivity'), confidence multiplier, or the share of "
        "remaining headroom closed (corpus rules); None for non-scoring rules (tags, flags).",
    )


class SeverityAssessment(BaseModel):
    """Severity verdict for a single finding; entity/span live on the wrapped detection."""

    model_config = {"extra": "forbid"}

    level: SeverityLevel
    risk_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0, description="Finding confidence used, after any rescue discount")
    needs_review: bool = False
    compliance_tags: List[Regulation] = Field(default_factory=list)
    rule_trace: List[RuleFired] = Field(default_factory=list)


class AssessedFinding(BaseModel):
    """A detection paired with its severity verdict; the detection is never mutated."""

    model_config = {"extra": "forbid"}

    detection: CombinedDetectionRow
    assessment: SeverityAssessment
    location: Optional[str] = Field(
        default=None,
        description="Where this sits: 'file.txt' for a document, 'column (row 3)' for a cell",
    )


class EntitySeverityRollup(BaseModel):
    model_config = {"extra": "forbid"}

    count: int
    max_level: SeverityLevel
    mean_risk_score: float
    compliance_tags: List[Regulation] = Field(default_factory=list)


class ComplianceStat(BaseModel):
    model_config = {"extra": "forbid"}

    count: int
    max_level: SeverityLevel


class RecordRiskProfile(BaseModel):
    """How dangerous one record is. Replaces per-character density, which measured clutter:
    ten names in a document is one identifier type, not ten times the risk."""

    model_config = {"extra": "forbid"}

    finding_count: int = 0
    risk_mass: float = 0.0
    strong_identifier_types: int = 0
    worst_level: SeverityLevel = SeverityLevel.INFO
    is_singleton: bool = False


class ExposureBreakdown(BaseModel):
    """Why the exposure index is what it is."""

    model_config = {"extra": "forbid"}

    severity_share: float = Field(
        default=0.0, description="Share of findings at high or critical"
    )
    uniqueness: Optional[float] = Field(
        default=None, description="Share of records below k_threshold; None = not measured"
    )
    mode: Literal["severity_only", "severity_x_uniqueness"] = "severity_only"
    critical_floor_applied: bool = False
    record_count: int = Field(default=0, description="Records scanned, whether or not reid ran")
    min_population: int = Field(
        default=0, description="Records needed before uniqueness is measured at all"
    )


class HipaaIdentifier(str, Enum):
    """The 18 HIPAA Safe Harbor identifier categories."""

    NAMES = "names"
    GEOGRAPHIC_SUBDIVISION = "geographic_subdivision"
    DATES = "dates"
    TELEPHONE = "telephone"
    FAX = "fax"
    EMAIL = "email"
    SSN = "ssn"
    MEDICAL_RECORD_NUMBER = "medical_record_number"
    HEALTH_PLAN_BENEFICIARY_NUMBER = "health_plan_beneficiary_number"
    ACCOUNT_NUMBER = "account_number"
    CERTIFICATE_LICENSE_NUMBER = "certificate_license_number"
    VEHICLE_IDENTIFIER = "vehicle_identifier"
    DEVICE_IDENTIFIER = "device_identifier"
    URL = "url"
    IP_ADDRESS = "ip_address"
    BIOMETRIC_IDENTIFIER = "biometric_identifier"
    FULL_FACE_PHOTO = "full_face_photo"
    OTHER_UNIQUE_ID = "other_unique_id"


class HipaaIdentifierStat(BaseModel):
    model_config = {"extra": "forbid"}

    finding_count: int = 0
    entities: List[str] = Field(default_factory=list)


class ReidSection(BaseModel):
    """Corpus re-identification summary, sourced from openmed.risk (kanon_report).

    The named field lists matter as much as k: grouping on one weak trait makes a dataset
    look safe, so a reader needs to see what k was actually computed from.
    """

    model_config = {"extra": "forbid"}

    k_min: Optional[int] = None
    reid_rate: Optional[float] = Field(
        default=None, description="None = not measured; needs an original/scrubbed pair to compare"
    )
    leakage_rate: Optional[float] = Field(
        default=None, description="None = not measured; needs an original/scrubbed pair to compare"
    )
    singleton_count: int = 0
    record_count: int = 0
    k_threshold: int = 5
    records_below_k_threshold: int = Field(
        default=0, description="Convention: a dataset is broadly considered de-identified when <1% sit below k=5"
    )
    quasi_identifiers: List[str] = Field(
        default_factory=list, description="Fields that formed the grouping key k was computed from"
    )
    sensitive_attributes: List[str] = Field(
        default_factory=list, description="Fields treated as the protected values"
    )


class ResidualSeverity(BaseModel):
    """Exposure before vs after de-identification — the point of running a policy at all.

    Findings are re-scored against what the scrub actually left: a masked value carries no
    residual risk, a coarsened one carries what its precision keeps, a surrogate keeps a
    little because records stay linkable.
    """

    model_config = {"extra": "forbid"}

    exposure_index_before: float = Field(ge=0.0, le=100.0)
    exposure_index_after: float = Field(ge=0.0, le=100.0)
    severity_before: Dict[SeverityLevel, int] = Field(default_factory=dict)
    severity_after: Dict[SeverityLevel, int] = Field(default_factory=dict)


class SensitiveDataReadinessReport(BaseModel):
    """Top-level v1 assessment artifact — the product's first user-visible deliverable.

    Reports *exposure*, not readiness: readiness is relative to an intended use.
    Attach ``policy_plan`` (from the policy shim) when a target OpenMed profile is known —
    that plan is what turns exposure into a de-identification readiness view.
    """

    model_config = {"extra": "forbid"}

    findings: List[AssessedFinding] = Field(default_factory=list)
    severity_histogram: Dict[SeverityLevel, int] = Field(default_factory=dict)
    per_entity: Dict[str, EntitySeverityRollup] = Field(default_factory=dict)
    per_record: Dict[str, RecordRiskProfile] = Field(default_factory=dict)
    compliance_summary: Dict[Regulation, ComplianceStat] = Field(default_factory=dict)
    hipaa_checklist: Dict[HipaaIdentifier, HipaaIdentifierStat] = Field(default_factory=dict)
    review_queue: List[AssessedFinding] = Field(default_factory=list)
    reidentification: Optional[ReidSection] = None
    exposure_index: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="0 = nothing sensitive found, 100 = maximally exposed. Not a grade: "
        "whether this level of exposure is acceptable depends on the intended use.",
    )
    exposure_breakdown: ExposureBreakdown = Field(default_factory=ExposureBreakdown)
    # axis (column or document) -> severity -> count. Deferred: needs real location labels.
    heatmap: Dict[str, Dict[SeverityLevel, int]] = Field(default_factory=dict)
    policy_plan: Optional[PolicyPlanSection] = Field(
        default=None,
        description="OpenMed policy action plan for these findings; None if no policy requested",
    )
    utility: Optional[UtilityLoss] = Field(
        default=None,
        description="Analytic value destroyed by the executed scrub; None until a policy is executed",
    )
    optimization: Optional[Any] = Field(
        default=None,
        description="What the optimizer chose per entity and why; None unless optimize= was set",
    )
    residual_severity: Optional[ResidualSeverity] = Field(
        default=None,
        description="Exposure before vs after the scrub; None until a policy is executed",
    )


__all__ = [
    "SeverityLevel",
    "Regulation",
    "RuleFired",
    "SeverityAssessment",
    "AssessedFinding",
    "EntitySeverityRollup",
    "ComplianceStat",
    "RecordRiskProfile",
    "ExposureBreakdown",
    "HipaaIdentifier",
    "HipaaIdentifierStat",
    "ReidSection",
    "ResidualSeverity",
    "SensitiveDataReadinessReport",
    "PolicyPlanSection",
    "UtilityLoss",
]
