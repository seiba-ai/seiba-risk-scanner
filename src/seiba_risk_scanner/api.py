"""The declared surface a downstream consumer imports.

One module, so a consumer depends on a contract rather than on internal paths: what
this re-exports is supported, everything else is free to move.

    from seiba_risk_scanner.api import SeibaScanner, SeverityResolver, fingerprint
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from seiba_risk_scanner import __version__
from seiba_risk_scanner.assessment.models import (
    HipaaIdentifier,
    Regulation,
    RuleFired,
    SeverityAssessment,
    SeverityLevel,
)
from seiba_risk_scanner.assessment.optimize import (
    ActionOptimizer,
    OptimizerConfig,
    OptimizerPlan,
    Privacy,
    resolve_config,
)
from seiba_risk_scanner.assessment.report import HIPAA_IDENTIFIER_MAP
from seiba_risk_scanner.assessment.residual import ResidualRisk, residual_risk, residual_score
from seiba_risk_scanner.assessment.resolver import (
    DEFAULT_BASE_SCORES,
    DEFAULT_THRESHOLDS,
    SeverityResolver,
    level_for,
    review_reason,
)
from seiba_risk_scanner.assessment.utility import (
    DEFAULT_UTILITY_WEIGHTS,
    UtilityLoss,
    UtilityWeights,
    utility_loss,
)
from seiba_risk_scanner.classification_engine.deterministic_detectors import validators
from seiba_risk_scanner.classification_engine.deterministic_detectors.validators_config import (
    ValidatorName,
)
from seiba_risk_scanner.classification_engine.ontologies.gazetteer import (
    CanonicalTerm,
    GazetteerIndex,
    GazetteerMatch,
    get_default_index,
    normalize_term,
)
from seiba_risk_scanner.classification_engine.ontologies.gazetteer.index import _ARTIFACT_PATH
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    DataClass,
    EntityConfig,
    load_entity_configs,
)
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
    ContextCandidate,
    Origin,
    PipelineStageResult,
    SpanAlternate,
)
from seiba_risk_scanner.config import (
    DEFAULT_MIN_FUSED_CONFIDENCE,
    FusionConfig,
    NERBackendName,
    ScannerConfig,
)
from seiba_risk_scanner.policy import (
    LADDERS,
    ActionRecord,
    PolicyPlanSection,
    PolicyResolver,
    execute_plan,
    generalize,
    scrub_documents,
    scrub_rows,
    scrub_text,
)
from seiba_risk_scanner.policy.generalize import precision_factor
from seiba_risk_scanner.scanner import SeibaScanner

_ONTOLOGY_DIR = Path(__file__).resolve().parent / "classification_engine" / "ontologies"


def _digest(*paths: Path) -> str:
    """Stable short hash over file contents, in sorted path order."""
    h = hashlib.sha256()
    for path in sorted(p for p in paths if p.exists()):
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


@lru_cache(maxsize=4)
def fingerprint(ner_backend: str = "openmed", ner_model: Optional[str] = None) -> Dict[str, Any]:
    """Identity of everything that decides what this scanner detects.

    Records the artifacts, not just the version: the ontologies are editable config, so
    two runs on one release can still disagree. A consumer stores this beside its
    results to tell apart *what* changed — code, rules, dictionary, or model.
    """
    from seiba_risk_scanner.classification_engine.ner.backends.openmed_backend import (
        DEFAULT_PII_MODEL,
    )

    return {
        "version": __version__,
        "ontologies": _digest(*_ONTOLOGY_DIR.glob("*.yaml")),
        "gazetteer": _digest(_ARTIFACT_PATH),
        "gazetteer_artifact": _ARTIFACT_PATH.name,
        "ner_backend": ner_backend,
        "ner_model": ner_model or DEFAULT_PII_MODEL,
    }


__all__ = [
    # detection
    "SeibaScanner", "ScannerConfig", "NERBackendName", "FusionConfig",
    "DEFAULT_MIN_FUSED_CONFIDENCE",
    "PipelineStageResult", "CombinedDetectionRow", "Origin", "ContextCandidate",
    "SpanAlternate",
    # ontology
    "DataClass", "EntityConfig", "load_entity_configs",
    # severity
    "SeverityResolver", "SeverityAssessment", "SeverityLevel", "RuleFired", "Regulation",
    "HipaaIdentifier", "HIPAA_IDENTIFIER_MAP", "level_for", "review_reason",
    "DEFAULT_BASE_SCORES", "DEFAULT_THRESHOLDS",
    # gazetteer — wanted beyond privacy (terminology normalization, coding coverage)
    "GazetteerIndex", "GazetteerMatch", "CanonicalTerm", "get_default_index", "normalize_term",
    # validators — wanted beyond privacy (format/identifier validity)
    "validators", "ValidatorName",
    # de-identification
    "PolicyResolver", "PolicyPlanSection", "ActionRecord", "execute_plan",
    "scrub_documents", "scrub_rows", "scrub_text", "generalize", "LADDERS",
    "precision_factor",
    "ActionOptimizer", "OptimizerConfig", "OptimizerPlan", "Privacy", "resolve_config",
    "utility_loss", "UtilityLoss", "UtilityWeights", "DEFAULT_UTILITY_WEIGHTS",
    "residual_risk", "residual_score", "ResidualRisk",
    # provenance
    "__version__", "fingerprint",
]
