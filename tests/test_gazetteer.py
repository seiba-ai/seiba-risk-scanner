"""Gazetteer dictionary detection + normalization, and the structured key-NER gate."""

from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
for _p in (repo_root / "src", repo_root):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from seiba_risk_scanner import SeibaScanner  # noqa: E402
from seiba_risk_scanner.classification_engine.deterministic_detectors.deterministic_detector import (  # noqa: E402
    gazetteer_detect,
)
from seiba_risk_scanner.classification_engine.ontologies.gazetteer import (  # noqa: E402
    get_default_index,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (  # noqa: E402
    load_entity_configs,
)
from seiba_risk_scanner.scanner import _decisive_key_entities  # noqa: E402


def test_index_matches_and_types_clinical_terms():
    idx = get_default_index()
    got = {m.text.lower(): m.term.entity for m in idx.iter_matches(
        "Prescribed sertraline and aspirin for depressive disorder and hypertension."
    )}
    assert got["sertraline"] == "medication_name"
    assert got["aspirin"] == "medication_name"  # RxNorm wins the disease/drug collision
    assert got["depressive disorder"] == "medical_condition"


def test_normalize_resolves_canonical_and_ignores_unknown():
    idx = get_default_index()
    assert idx.normalize("aspirin").entity == "medication_name"
    assert idx.normalize("ASPIRIN").canonical == "aspirin"  # case-insensitive
    assert idx.normalize("not a medical phrase at all") is None


def test_ordinary_prose_is_not_flagged():
    idx = get_default_index()
    prose = "The man walked to the city for a cold drink and a good time by the river."
    assert list(idx.iter_matches(prose)) == []


def test_gazetteer_detect_emits_phi_rows_with_canonical_provenance():
    rows = gazetteer_detect("history of type 2 diabetes mellitus")
    assert rows and rows[0].entity_id == "phi_entity_ontology::medical_condition"
    assert rows[0].provenance and "gazetteer_canonical" in rows[0].provenance


def test_scanner_surfaces_health_entities_end_to_end():
    scanner = SeibaScanner(skip_ner=True)  # isolate deterministic + gazetteer
    res = scanner.classify_text("Patient on metformin, diagnosed with hypertension.")
    entities = {d.entity for d in res.detections}
    assert "medication_name" in entities
    assert "medical_condition" in entities


def test_decisive_key_resolution_is_conservative():
    configs = load_entity_configs()
    d = _decisive_key_entities(
        ["city", "person_city", "patient_name", "name", "medication", "zip_code"], configs
    )
    assert d["city"] == "pii_entity_ontology::city"
    assert d["person_city"] == "pii_entity_ontology::city"  # head noun, robust to prefix
    # "name" is a generic token inside medication_name; must not mis-resolve there.
    assert d["patient_name"] not in {"phi_entity_ontology::medication_name"}
    assert d["name"] in {None, "pii_entity_ontology::person_names"}
    assert d["medication"] is None  # medication_name vs medication_dosage -> ambiguous
    assert d["zip_code"] == "pii_entity_ontology::zip_code"


def test_decisive_column_key_relabels_the_ner_span():
    """A compact cell is typed by its column, not by what NER guessed the token is.

    The span must be *relabelled* rather than dropped: contextual scoring can only
    rescore an existing span, so removing it would leave the cell undetected.
    """
    res = SeibaScanner().classify_structured_text(
        [{"city": "Austin", "patient_name": "John Smith"}]
    )
    by_text = {d.text: d.entity for d in res.detections}
    assert by_text.get("Austin") == "city"  # NER reads a person here; the column wins
    assert by_text.get("John Smith") == "person_names"  # name column unaffected
