"""Unit tests for the OpenMed policy shim (resolve + execute)."""

from __future__ import annotations

import pytest

from seiba_risk_scanner.assessment import ReadinessAssessor
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    DataClass,
    load_all_ontologies,
    load_ontology,
)
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
    PipelineStageResult,
)
from seiba_risk_scanner.policy import (
    DATA_CLASS_TO_POLICY_CLASS,
    PolicyResolver,
    apply_action_to_text,
    execute_plan,
    openmed_policy_class_for,
)
from seiba_risk_scanner.policy.bridge import DIRECT_IDENTIFIER, QUASI_IDENTIFIER


def _reload_configs():
    load_ontology.cache_clear()
    load_all_ontologies.cache_clear()
    return load_all_ontologies()


def row(entity_id: str, entity: str, text: str = "VALUE"):
    return CombinedDetectionRow(
        entity_id=entity_id,
        entity=entity,
        start=0,
        end=len(text),
        text=text,
        confidence=0.95,
        confidence_deterministic=0.95,
        confidence_contextual=0.0,
    )


@pytest.fixture(scope="module")
def configs():
    return _reload_configs()


def test_ontology_de_identifier_coverage(configs):
    mapped = [c for c in configs.values() if c.de_identifier]
    nulls = [c for c in configs.values() if not c.de_identifier]
    # 84 = 83 + account_reference_number, split out of unique_identifier so the HIPAA
    # checklist can report ACC- values under "account number" instead of "other unique id".
    assert len(configs) == 84
    assert len(mapped) == 65
    assert len(nulls) == 19
    assert configs["pii_entity_ontology::ssn"].de_identifier == "SSN"
    assert configs["pii_entity_ontology::us_itin"].de_identifier is None
    assert configs["phi_entity_ontology::dna_sequences"].de_identifier is None
    assert configs["phi_entity_ontology::genomic_variants"].de_identifier is None


def test_data_class_map_treats_genetic_as_direct():
    assert openmed_policy_class_for(DataClass.GENETIC_DATA) == DIRECT_IDENTIFIER
    assert openmed_policy_class_for(DataClass.SENSITIVE_ATTRIBUTE) == QUASI_IDENTIFIER
    assert openmed_policy_class_for(DataClass.NEUTRAL) is None
    assert set(DATA_CLASS_TO_POLICY_CLASS) == {
        DataClass.DIRECT_IDENTIFIER,
        DataClass.FINANCIAL_DATA,
        DataClass.BIOMETRIC_IDENTIFIER,
        DataClass.DEVICE_IDENTIFIER,
        DataClass.GENETIC_DATA,
        DataClass.QUASI_IDENTIFIER,
        DataClass.SENSITIVE_ATTRIBUTE,
    }


def test_exact_ssn_matches_openmed_action_for(configs):
    from openmed.core.policy import load_policy

    profile = load_policy("hipaa_safe_harbor")
    expected = profile.action_for("SSN")
    record = PolicyResolver("hipaa_safe_harbor", configs=configs).resolve_one(
        row("pii_entity_ontology::ssn", "ssn", "123-45-6789")
    )
    assert record.source == "openmed_action_for"
    assert record.openmed_label == "SSN"
    assert record.action == expected == "mask"


def test_us_itin_class_fallback_gdpr_replace_not_keep(configs):
    """Null label must NOT go through action_for(OTHER)→CLINICAL keep under GDPR."""
    record = PolicyResolver("gdpr_pseudonymization", configs=configs).resolve_one(
        row("pii_entity_ontology::us_itin", "us_itin", "912-34-5678")
    )
    assert record.source == "openmed_policy_label_actions"
    assert record.openmed_label is None
    assert record.openmed_policy_class == DIRECT_IDENTIFIER
    assert record.action == "replace"
    assert "keep" not in record.detail or "→ replace" in record.detail


def test_genetic_class_fallback_is_direct_not_clinical(configs):
    gdpr = PolicyResolver("gdpr_pseudonymization", configs=configs).resolve_one(
        row("phi_entity_ontology::dna_sequences", "dna_sequences", "ATCG")
    )
    assert gdpr.openmed_policy_class == DIRECT_IDENTIFIER
    assert gdpr.action == "replace"  # not clinical keep

    hipaa = PolicyResolver("hipaa_safe_harbor", configs=configs).resolve_one(
        row("phi_entity_ontology::genomic_variants", "genomic_variants", "BRCA1")
    )
    assert hipaa.openmed_policy_class == DIRECT_IDENTIFIER
    assert hipaa.action == "mask"


def test_biometric_class_fallback_direct(configs):
    record = PolicyResolver("hipaa_safe_harbor", configs=configs).resolve_one(
        row("phi_entity_ontology::fingerprints", "fingerprints", "fp-hash")
    )
    assert record.source == "openmed_policy_label_actions"
    assert record.openmed_policy_class == DIRECT_IDENTIFIER
    assert record.action == "mask"


def test_neutral_keeps(configs):
    record = PolicyResolver("hipaa_safe_harbor", configs=configs).resolve_one(
        row("phi_entity_ontology::measurement_units", "measurement_units", "mg/dL")
    )
    assert record.source == "neutral_keep"
    assert record.action == "keep"


def test_execute_class_fallback_replace_downgrades_to_seiba_mask(configs):
    record = PolicyResolver("gdpr_pseudonymization", configs=configs).resolve_one(
        row("pii_entity_ontology::us_itin", "us_itin", "912-34-5678")
    )
    assert record.action == "replace"
    executed = apply_action_to_text(record)
    assert executed.execute_fallback == "replace→mask"
    assert executed.replacement == "[US_ITIN]"


def test_execute_exact_replace_uses_anonymizer(configs):
    record = PolicyResolver("gdpr_pseudonymization", configs=configs).resolve_one(
        row("pii_entity_ontology::person_names", "person_names", "Alice Smith")
    )
    assert record.action == "replace"
    assert record.openmed_label == "PERSON"
    executed = apply_action_to_text(record)
    assert executed.execute_fallback is None
    assert executed.replacement is not None
    assert executed.replacement != "Alice Smith"
    assert not executed.replacement.startswith("[")


def test_assessor_attaches_policy_plan(configs):
    result = PipelineStageResult(
        detections=[
            row("pii_entity_ontology::ssn", "ssn", "123-45-6789"),
            row("pii_entity_ontology::us_itin", "us_itin", "912-34-5678"),
        ]
    )
    report = ReadinessAssessor(
        policy="hipaa_safe_harbor", execute_policy=False
    ).assess(result)
    assert report.policy_plan is not None
    assert report.policy_plan.policy_name == "hipaa_safe_harbor"
    assert report.policy_plan.exact_count >= 1
    assert report.policy_plan.class_fallback_count >= 1
    assert report.policy_plan.executed is False

    executed = ReadinessAssessor(
        policy="gdpr_pseudonymization", execute_policy=True
    ).assess(result)
    assert executed.policy_plan is not None
    assert executed.policy_plan.executed is True
    itin = next(
        r for r in executed.policy_plan.records if r.entity == "us_itin"
    )
    assert itin.replacement == "[US_ITIN]"


def test_execute_plan_marks_executed(configs):
    plan = PolicyResolver("hipaa_safe_harbor", configs=configs).resolve(
        [row("pii_entity_ontology::ssn", "ssn", "123-45-6789")]
    )
    done = execute_plan(plan)
    assert done.executed is True
    assert done.records[0].replacement == "[SSN]"
