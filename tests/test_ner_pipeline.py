"""NER merge and override tests (no downloaded spaCy models required)."""

import sys
import types

from seiba_risk_scanner import SeibaScanner, make_custom_ner_runner, make_hf_ner_runner
from seiba_risk_scanner.classification_engine.ner.backends.openmed_backend import (
    OpenMedBackend,
    _PERSON_NAMES_EID,
)
from seiba_risk_scanner.classification_engine.ner.ner_runner import NerSpanRecord
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    load_all_ontologies,
    load_ner_label_to_entity_map,
    resolve_entity_alias,
)


def test_skip_ner_matches_deterministic_plus_contextual_scores():
    sdk = SeibaScanner(verbose=False, skip_ner=True)
    res = sdk.classify_text("email me at x@y.co")
    assert res.detections
    d0 = res.detections[0]
    assert d0.entity == "email_address"
    assert d0.confidence_contextual > 0.0


def test_ner_override_adds_person_span():
    def fake_ner(text: str):
        if "Jane" not in text:
            return []
        i = text.index("Jane")
        return [
            NerSpanRecord(
                start=i,
                end=i + 4,
                text="Jane",
                label="PERSON",
                entity_id="pii_entity_ontology::person_names",
                confidence_ner=0.78,
                ontology="pii_entity_ontology",
                pipeline="spacy",
            )
        ]

    sdk = SeibaScanner(verbose=False, ner_runner_override=fake_ner)
    res = sdk.classify_text("seen with Jane at clinic")
    person = [d for d in res.detections if d.entity == "person_names"]
    assert person
    assert person[0].ner_label == "PERSON"
    assert person[0].confidence_ner == 0.78


def test_ner_override_conflict_contextual_picks_winner():
    """Same span: deterministic email vs NER PERSON — fusion + context picks one."""

    def fake_ner(text: str):
        if "x@y.co" not in text:
            return []
        i = text.index("x@y.co")
        return [
            NerSpanRecord(
                start=i,
                end=i + len("x@y.co"),
                text="x@y.co",
                label="PERSON",
                entity_id="pii_entity_ontology::person_names",
                confidence_ner=0.78,
                ontology="pii_entity_ontology",
                pipeline="spacy",
            )
        ]

    sdk = SeibaScanner(verbose=False, ner_runner_override=fake_ner)
    res = sdk.classify_text("email me at x@y.co")
    assert res.detections
    # Email context ("email") strongly supports email_address over person_names.
    assert res.detections[0].entity == "email_address"


def test_load_ner_label_map():
    m = load_ner_label_to_entity_map()
    assert m["PERSON"] == ["pii_entity_ontology::person_names"]
    assert m["NORP"] == [
        "pii_entity_ontology::nationality",
        "pii_entity_ontology::religious_affiliation",
    ]


def test_entity_config_loads_ner_confidence_weight():
    cfgs = load_all_ontologies()
    pn = cfgs["pii_entity_ontology::person_names"]
    assert pn.ner_confidence_weight == 0.50
    assert pn.classification_category == "PII"


def test_openmed_label_map_drops_bic_keeps_swift_bic():
    """bic fires on all-caps words (98 FP / 0 TP); only swift_bic survives."""
    b = OpenMedBackend()  # loads label map only, no model download
    assert "bic" not in b._label_map
    assert b._label_map["swift_bic"] == ("fin_entity_ontology::swift_bic", (), None)


def test_openmed_company_name_hospital_or_employer_never_dropped():
    """Care-facility context -> hospital; otherwise the person's employer (recall-first)."""
    b = OpenMedBackend()
    with_ctx = "Referred to Springfield Memorial Hospital yesterday."
    s, e = with_ctx.index("Springfield"), with_ctx.index("Hospital") + len("Hospital")
    assert b._resolve("company_name", with_ctx, s, e) == "phi_entity_ontology::hospital_names"
    no_ctx = "Invoice from TechCorp Industries is overdue."
    assert (
        b._resolve("company_name", no_ctx, no_ctx.index("TechCorp"), no_ctx.index(" is"))
        == "pii_entity_ontology::employer_organization"
    )


def test_openmed_merges_adjacent_person_names():
    text = "Patient Jennifer Smith called."
    rows = [
        NerSpanRecord(8, 16, "Jennifer", "first_name", _PERSON_NAMES_EID, 0.9, "pii_entity_ontology", "openmed"),
        NerSpanRecord(17, 22, "Smith", "last_name", _PERSON_NAMES_EID, 0.8, "pii_entity_ontology", "openmed"),
    ]
    merged = OpenMedBackend._merge_adjacent_person_names(rows, text)
    assert len(merged) == 1
    assert merged[0].text == "Jennifer Smith"
    assert (merged[0].start, merged[0].end) == (8, 22)
    assert merged[0].confidence_ner == 0.9


def test_openmed_clinical_model_passthrough_labels():
    """Non-PII model routes labels through as openmed::<label> with no map lookup."""
    b = OpenMedBackend(model_name="OpenMed/OpenMed-NER-DiseaseDetect-BigMed-560M")
    assert b._is_pii is False
    assert b._resolve("DISEASE", "acute myocardial infarction", 0, 5) == "openmed::DISEASE"


def _fake_raw_model(text):
    i = text.find("Jane")
    spans = [{"start": i, "end": i + 4, "entity_group": "PER", "score": 0.9}] if i >= 0 else []
    j = text.find("Acme")
    if j >= 0:  # unmapped label -> dropped
        spans.append({"start": j, "end": j + 4, "label": "ORG_CO", "score": 0.8})
    return spans


def test_custom_ner_runner_dict_map():
    runner = make_custom_ner_runner(_fake_raw_model, {"PER": "pii_entity_ontology::person_names"})
    recs = runner("Met Jane at Acme.")
    assert [(r.text, r.entity_id, r.ontology, r.pipeline) for r in recs] == [
        ("Jane", "pii_entity_ontology::person_names", "pii_entity_ontology", "custom")
    ]
    assert abs(recs[0].confidence_ner - 0.65 * 0.9) < 1e-9  # DEFAULT_NER_CONFIDENCE_WEIGHT * score


def test_custom_ner_runner_yaml_path_and_scanner(tmp_path):
    map_file = tmp_path / "custom_labels.yaml"
    map_file.write_text("PER: pii_entity_ontology::person_names\n", encoding="utf-8")
    runner = make_custom_ner_runner(_fake_raw_model, map_file)
    sdk = SeibaScanner(verbose=False, ner_runner_override=runner)
    res = sdk.classify_text("Met Jane at Acme.")
    person = [d for d in res.detections if d.entity == "person_names"]
    assert person and person[0].ner_label == "PER"


def test_backend_run_batch_default_loops_run():
    """ABC default run_batch loops run() so non-batching backends work unchanged."""
    from seiba_risk_scanner.classification_engine.ner.backends.base import NERBackend

    class _Fake(NERBackend):
        @property
        def backend_name(self):
            return "fake"

        def run(self, text, *, configs, verbose=False, timings=None):
            i = text.find("Jane")
            return (
                [NerSpanRecord(i, i + 4, "Jane", "PER", "pii_entity_ontology::person_names",
                               0.9, "pii_entity_ontology", "fake")]
                if i >= 0 else []
            )

    out = _Fake().run_batch(["Jane here", "nothing", "and Jane"], configs={})
    assert [len(x) for x in out] == [1, 0, 1]
    assert out[2][0].text == "Jane"


def test_classify_texts_alignment_and_empty():
    """classify_texts returns one result per input in order; empty inputs stay aligned."""
    sdk = SeibaScanner(verbose=False, skip_ner=True)  # deterministic-only, no model
    out = sdk.classify_texts(["email me at a@b.co", "", "reach me at 415-555-0100"])
    assert len(out) == 3
    assert any(d.entity == "email_address" for d in out[0].detections)
    assert out[1].detections == []
    assert any(d.entity == "phone_number" for d in out[2].detections)


def test_web_url_detects_scheme_less():
    """Widened web_url pattern + validator catch www. URLs (previously required http://)."""
    sdk = SeibaScanner(verbose=False, skip_ner=True)
    res = sdk.classify_text("Visit www.example.com today.")
    assert any(d.entity == "web_url" and d.text == "www.example.com" for d in res.detections)


def test_ner_skipped_on_non_prose_cell():
    """Short-circuit: cells with no >=2-letter word skip the NER call entirely."""
    called = {"n": 0}

    def fake_ner(text):
        called["n"] += 1
        return []

    sdk = SeibaScanner(verbose=False, ner_runner_override=fake_ner)
    sdk.classify_text("0987654321")  # pure digits -> NER skipped
    sdk.classify_text("2024-01-15")  # date -> NER skipped
    assert called["n"] == 0
    sdk.classify_text("Contact Jane")  # prose -> NER runs
    assert called["n"] == 1


def test_hf_ner_runner_runs_any_transformer(monkeypatch):
    """make_hf_ner_runner builds an HF token-classification pipeline lazily and maps it."""
    calls = {"built": 0}

    def fake_pipeline(task, model, aggregation_strategy):
        assert task == "token-classification"
        calls["built"] += 1
        return lambda text: [{"entity_group": "PER", "start": text.find("Jane"),
                              "end": text.find("Jane") + 4, "score": 0.88}]

    monkeypatch.setitem(sys.modules, "transformers",
                        types.SimpleNamespace(pipeline=fake_pipeline))
    runner = make_hf_ner_runner("some/hf-model", {"PER": "pii_entity_ontology::person_names"})
    recs = runner("Met Jane today.")
    assert calls["built"] == 1  # pipeline built lazily on first call
    assert [(r.text, r.entity_id, r.pipeline) for r in recs] == [
        ("Jane", "pii_entity_ontology::person_names", "hf")
    ]
    runner("Jane again.")
    assert calls["built"] == 1  # reused, not rebuilt


def test_is_a_reports_subtype_detections_as_the_parent_entity():
    """A physician is a person: the clinical phrases still detect, person_names is reported.

    Guessing *which kind* of person a name belongs to must never decide whether the name
    is reported at all, so the subtype never reaches the output.
    """
    configs = load_all_ontologies()
    assert configs["phi_entity_ontology::physician_names"].is_a == _PERSON_NAMES_EID
    assert resolve_entity_alias("phi_entity_ontology::physician_names", configs) == _PERSON_NAMES_EID
    # An entity without a parent, and an unknown id, resolve to themselves.
    assert resolve_entity_alias(_PERSON_NAMES_EID, configs) == _PERSON_NAMES_EID
    assert resolve_entity_alias("nope::nope", configs) == "nope::nope"

    def fake_ner(text):
        start = text.find("Alice Nguyen")
        return [
            NerSpanRecord(
                start=start,
                end=start + len("Alice Nguyen"),
                text="Alice Nguyen",
                label="PERSON",
                entity_id="phi_entity_ontology::physician_names",
                confidence_ner=0.9,
                ontology="phi_entity_ontology",
                pipeline="test",
            )
        ]

    sdk = SeibaScanner(verbose=False, ner_runner_override=fake_ner)
    res = sdk.classify_text("Attending physician: Dr. Alice Nguyen, MD reviewed the chart.")
    names = [r for r in res.detections if r.text == "Alice Nguyen"]
    assert names, "physician name should still be detected"
    assert all(r.entity_id == _PERSON_NAMES_EID for r in names)
    assert not any("physician_names" in r.entity_id for r in res.detections)


def test_is_a_resolution_survives_a_reference_cycle():
    """A malformed ontology must degrade to the un-aliased entity, not hang or raise."""
    from dataclasses import replace as _replace

    configs = dict(load_all_ontologies())
    a, b = "pii_entity_ontology::person_names", "phi_entity_ontology::physician_names"
    configs[a] = _replace(configs[a], is_a=b)  # a -> b -> a
    assert resolve_entity_alias(a, configs) in {a, b}
    assert resolve_entity_alias(b, configs) in {a, b}
