"""Unit tests for the assessment layer (severity engine).

Pure-function coverage over the scoring rules, plus a few end-to-end checks through
ReadinessAssessor with synthetic detections — no scanner, no NER, deterministic.
"""
from __future__ import annotations

import pytest

from seiba_risk_scanner.assessment import (
    ReadinessAssessor,
    Regulation,
    SeverityLevel,
    SeverityResolver,
    to_markdown,
)
from seiba_risk_scanner.assessment.assessor import BOOSTABLE_CLASSES, STRONG_CLASSES
from seiba_risk_scanner.assessment.report import ReportBuilder
from seiba_risk_scanner.assessment.resolver import DEFAULT_BASE_SCORES, level_for, review_reason
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import DataClass
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
    PipelineStageResult,
)

CONFIGS = None  # loaded once via the assessor below


def row(entity_id, entity, *, conf=0.95, rescue=False, subtype=None, row_idx=None, column=None):
    provenance = {}
    if row_idx is not None:
        provenance["row"] = row_idx
    if column is not None:
        provenance["column"] = column
    return CombinedDetectionRow(
        entity_id=entity_id,
        entity=entity,
        start=0,
        end=len(entity),
        text=entity,
        confidence=conf,
        confidence_deterministic=conf,
        confidence_contextual=0.0,
        rescue_applied=rescue,
        detected_subtype=subtype,
        provenance=provenance or None,
    )


# --------------------------------------------------------------------------- resolver


def test_base_scores_cover_every_data_class():
    # A missing class would silently fall back to DEFAULT_BASE; catch that here.
    assert set(DEFAULT_BASE_SCORES) == set(DataClass)


def test_severity_is_base_only_confidence_does_not_move_it():
    r = SeverityResolver()
    configs = ReadinessAssessor().configs
    ssn = configs["pii_entity_ontology::ssn"]
    high_conf = r.resolve(row("pii_entity_ontology::ssn", "ssn", conf=0.95), ssn)
    low_conf = r.resolve(row("pii_entity_ontology::ssn", "ssn", conf=0.40), ssn)
    assert high_conf.risk_score == low_conf.risk_score == pytest.approx(0.90)


def test_level_thresholds_are_inclusive_lower_bounds():
    t = SeverityResolver().thresholds
    assert level_for(0.65, t) is SeverityLevel.HIGH
    assert level_for(0.649, t) is SeverityLevel.MEDIUM
    assert level_for(0.0, t) is SeverityLevel.INFO


def test_review_routes_severe_and_unsure_only():
    # high severity + low confidence -> review; high + confident -> not; low severity never.
    assert review_reason(SeverityLevel.HIGH, 0.4, False) == "low_confidence"
    assert review_reason(SeverityLevel.HIGH, 0.9, False) is None
    assert review_reason(SeverityLevel.MEDIUM, 0.1, False) is None
    assert review_reason(SeverityLevel.HIGH, 0.9, True) == "rescue"


def test_bare_ner_name_at_050_still_reaches_review():
    # NER person hits land at exactly 0.50; the gate is < 0.6 so they must qualify.
    assert review_reason(SeverityLevel.HIGH, 0.50, False) == "low_confidence"


def test_compliance_tags_from_category_and_class():
    configs = ReadinessAssessor().configs
    r = SeverityResolver()
    dob = r.resolve(row("phi_entity_ontology::date_of_birth", "date_of_birth"),
                    configs["phi_entity_ontology::date_of_birth"])
    assert Regulation.HIPAA in dob.compliance_tags  # PHI category
    card = r.resolve(row("fin_entity_ontology::credit_card_number", "credit_card_number"),
                     configs["fin_entity_ontology::credit_card_number"])
    assert Regulation.PCI in card.compliance_tags
    neutral = r.resolve(row("pii_entity_ontology::uuid_guid", "uuid_guid"),
                        configs["pii_entity_ontology::uuid_guid"])
    assert neutral.compliance_tags == []  # NEUTRAL gets no personal-data regs


# --------------------------------------------------------------------------- corpus math


def test_toward_ceiling_never_overflows_and_is_monotonic():
    a = ReadinessAssessor()
    assert a._toward_ceiling(0.9, 0.45) < 1.0
    assert a._toward_ceiling(0.9, 1.0) == 1.0
    assert a._toward_ceiling(0.8, 0.3) < a._toward_ceiling(0.9, 0.3)  # order preserved


def test_cooccurrence_strength_graded_then_capped():
    a = ReadinessAssessor()
    assert a._cooccurrence_strength(1) == 0.0  # below threshold
    assert a._cooccurrence_strength(2) == pytest.approx(0.15)
    assert a._cooccurrence_strength(3) == pytest.approx(0.30)
    assert a._cooccurrence_strength(20) == a.cooccurrence_cap  # capped


def test_lone_finding_cannot_be_critical():
    # CRITICAL must be earned from corpus context; a single scored finding tops out at HIGH.
    a = ReadinessAssessor()
    worst = max(DEFAULT_BASE_SCORES.values())
    assert level_for(worst, a.thresholds) is not SeverityLevel.CRITICAL


def test_boostable_excludes_quasi_and_device():
    assert DataClass.QUASI_IDENTIFIER not in BOOSTABLE_CLASSES
    assert DataClass.DEVICE_IDENTIFIER not in BOOSTABLE_CLASSES
    assert STRONG_CLASSES <= BOOSTABLE_CLASSES


# --------------------------------------------------------------------------- end to end


def _cell(entity_id, entity, text, *, conf=0.95, row_idx=None, column=None):
    r = row(entity_id, entity, conf=conf, row_idx=row_idx, column=column)
    return r.model_copy(update={"text": text, "end": len(text)})


def _structured(n_unique_rows: int) -> PipelineStageResult:
    # Distinct zip per row so each record is a singleton (k=1) on the quasi-identifier.
    dets = []
    for i in range(n_unique_rows):
        dets.append(_cell("pii_entity_ontology::ssn", "ssn", f"123-45-{6000+i}", row_idx=i, column="ssn"))
        dets.append(_cell("pii_entity_ontology::email_address", "email_address", f"u{i}@ex.com", row_idx=i, column="email"))
        dets.append(_cell("pii_entity_ontology::zip_code", "zip_code", f"9{i:04d}", conf=0.8, row_idx=i, column="zip"))
    return PipelineStageResult(detections=dets)


def test_stacked_identifiers_in_unique_record_reach_critical():
    report = ReadinessAssessor().assess(_structured(12))
    levels = {f.assessment.level for f in report.findings if f.detection.entity != "zip_code"}
    assert SeverityLevel.CRITICAL in levels


def test_quasi_stays_medium_even_in_unique_records():
    report = ReadinessAssessor().assess(_structured(12))
    zips = [f for f in report.findings if f.detection.entity == "zip_code"]
    assert zips and all(f.assessment.level is SeverityLevel.MEDIUM for f in zips)


def test_uniqueness_not_measured_below_min_population():
    # Two rows is below min_population; report must not claim a k or apply singleton boosts.
    report = ReadinessAssessor().assess(_structured(2))
    assert report.reidentification is None
    assert report.exposure_breakdown.mode == "severity_only"
    boosts = [t for f in report.findings for t in f.assessment.rule_trace if t.rule_id == "reid:singleton"]
    assert boosts == []


def test_health_context_declaration_adds_hipaa():
    result = _structured(12)  # all PII entities, no PHI to infer from
    without = ReadinessAssessor().assess(result)
    assert Regulation.HIPAA not in without.compliance_summary
    with_ctx = ReadinessAssessor().assess(_structured(12), health_context=True)
    assert Regulation.HIPAA in with_ctx.compliance_summary


def test_exposure_index_discriminates():
    empty = ReadinessAssessor().assess(PipelineStageResult(detections=[]))
    loaded = ReadinessAssessor().assess(_structured(12))
    assert empty.exposure_index == 0.0
    assert loaded.exposure_index > empty.exposure_index


def test_critical_floor_holds_index_up():
    b = ReportBuilder()
    a = ReadinessAssessor(builder=b)
    report = a.assess(_structured(12))
    if any(f.assessment.level is SeverityLevel.CRITICAL for f in report.findings):
        assert report.exposure_index >= b.critical_floor


def test_detection_is_never_mutated():
    result = _structured(12)
    original = result.detections[0].model_copy(deep=True)
    ReadinessAssessor().assess(result)
    assert result.detections[0] == original


# --------------------------------------------------------------------------- render


def test_residual_severity_reports_before_and_after():
    report = ReadinessAssessor().assess(_structured(12))
    residual = report.residual_severity
    assert residual is not None
    assert residual.exposure_index_before == report.exposure_index
    # hipaa_safe_harbor masks everything, so nothing severe can survive it
    assert residual.exposure_index_after < residual.exposure_index_before


def test_keeping_everything_leaves_exposure_unchanged():
    """The before/after must react to the policy, not always report an improvement."""
    keep_all = {e: "keep" for e in ("ssn", "email_address", "zip_code")}
    report = ReadinessAssessor(action_overrides=keep_all).assess(_structured(12))
    residual = report.residual_severity
    assert residual.exposure_index_after == residual.exposure_index_before


def test_residual_severity_absent_without_execution():
    report = ReadinessAssessor(execute_policy=False).assess(_structured(12))
    assert report.residual_severity is None


def test_markdown_renders_key_sections():
    result = _structured(12)
    # a low-confidence name so the review section is exercised too
    result.detections.append(
        _cell("pii_entity_ontology::person_names", "person_names", "Jane Doe", conf=0.5, row_idx=0, column="name")
    )
    md = to_markdown(ReadinessAssessor().assess(result, health_context=True))
    for heading in (
        "Exposure index",
        "HIPAA Safe Harbor",
        "Where the risk is",
        "Human approval flagged entities",
        "Re-identification risk of individuals",
        "De-identification strength",
    ):
        assert heading in md
