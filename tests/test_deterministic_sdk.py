"""Smoke tests for deterministic SDK path and ontology merge."""

import re

import pandas as pd

from seiba_risk_scanner import SeibaScanner
from seiba_risk_scanner.classification_engine.deterministic_detectors.deterministic_detector import (
    DeterministicDetectionRow,
    deterministic_stage_result,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    load_all_ontologies,
)
from seiba_risk_scanner.classification_engine.deterministic_detectors import validators


def test_merge_preserves_duplicate_entity_names_across_ontologies():
    cfgs = load_all_ontologies()
    assert "pii_entity_ontology::dates" in cfgs
    assert "phi_entity_ontology::dates" in cfgs
    assert cfgs["pii_entity_ontology::dates"].name == "dates"
    assert cfgs["phi_entity_ontology::dates"].name == "dates"


def test_classify_deterministic_text_email():
    sdk = SeibaScanner()
    res = sdk.classify_deterministic_text("email me at x@y.co")
    assert res.stage == "deterministic"
    assert res.text_length == len("email me at x@y.co")
    assert any(d.entity == "email_address" for d in res.detections)


def test_classify_deterministic_text_empty():
    assert SeibaScanner().classify_deterministic_text("").detections == []


def test_classify_deterministic_structured_dataframe():
    df = pd.DataFrame([{"col": "reach me x@z.com"}])
    res = SeibaScanner().classify_deterministic_structured(df)
    assert res.detections
    d0 = res.detections[0]
    assert d0.provenance is not None
    assert d0.provenance.get("kind") == "dataframe"
    assert d0.provenance.get("column") == "col"


def test_classify_deterministic_text_phone_us_nanp():
    sdk = SeibaScanner()
    res = sdk.classify_deterministic_text("Call (310) 555-1234 today")
    assert any(d.entity == "phone_number" for d in res.detections)


def test_classify_deterministic_text_date_month_name():
    sdk = SeibaScanner()
    res = sdk.classify_deterministic_text("Application Date: May 15, 2024")
    assert any(d.entity == "dates" and "May" in d.text for d in res.detections)


def test_all_loaded_accepted_and_prohibited_patterns_compile():
    cfgs = load_all_ontologies()
    for cfg in cfgs.values():
        for p in cfg.accepted_patterns:
            re.compile(p)
        for p in cfg.prohibited_patterns:
            re.compile(p)


def test_deterministic_stage_result_dedupes_identical_span_keeps_higher_confidence():
    rows = [
        DeterministicDetectionRow(
            entity_id="a::low",
            entity="low",
            start=0,
            end=5,
            text="12345",
            confidence=0.5,
            ontology="a",
        ),
        DeterministicDetectionRow(
            entity_id="b::high",
            entity="high",
            start=0,
            end=5,
            text="12345",
            confidence=0.9,
            ontology="b",
        ),
    ]
    out = deterministic_stage_result(rows, text_length=10)
    assert len(out.detections) == 1
    assert out.detections[0].entity == "high"
    assert out.detections[0].confidence == 0.9


def test_validate_insurance_id_rejects_digit_only():
    ok, _ = validators.validate_insurance_id("12345678")
    assert ok is False


def test_deterministic_stage_result_respects_min_confidence():
    rows = [
        DeterministicDetectionRow(
            entity_id="x::a",
            entity="a",
            start=0,
            end=3,
            text="low",
            confidence=0.25,
            ontology="x",
        ),
        DeterministicDetectionRow(
            entity_id="x::b",
            entity="b",
            start=10,
            end=13,
            text="ok",
            confidence=0.55,
            ontology="x",
        ),
    ]
    out = deterministic_stage_result(rows, text_length=20, min_confidence=0.4)
    assert len(out.detections) == 1
    assert out.detections[0].entity == "b"
