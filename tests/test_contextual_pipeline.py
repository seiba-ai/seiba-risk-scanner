"""Tests for contextual phrase scoring and fused pipeline."""

from seiba_risk_scanner import SeibaScanner
from seiba_risk_scanner.classification_engine.contextual.contextual_words import (
    ContextualWordsScorer,
    fuse_confidence,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    load_all_ontologies,
)


def test_load_ontology_includes_contextual_phrases_for_email():
    cfgs = load_all_ontologies()
    email = cfgs["pii_entity_ontology::email_address"]
    assert "email" in email.contextual_phrases
    assert email.entity_id == "pii_entity_ontology::email_address"


def test_fuse_confidence_clamped():
    assert fuse_confidence(1.0, 1.0) == 1.0
    assert fuse_confidence(0.0, 0.0) == 0.0
    # boost-only: ctx=0 leaves deterministic unchanged
    assert fuse_confidence(1.0, 0.0) == 1.0
    # boost-only: never reduces deterministic confidence
    assert fuse_confidence(0.9, 0.25) >= 0.9


def test_contextual_scorer_zero_without_phrases_in_window():
    cfgs = load_all_ontologies()
    cfg = cfgs["pii_entity_ontology::email_address"]
    text = "reach me x@y.co"
    # span roughly at x@y.co
    start = text.index("x@")
    end = text.index("x@") + len("x@y.co")
    scorer = ContextualWordsScorer()
    s = scorer.score_span(text, start, end, cfg, 50, 25)
    assert s == 0.0


def test_contextual_scorer_nonzero_when_phrase_adjacent():
    cfgs = load_all_ontologies()
    cfg = cfgs["pii_entity_ontology::email_address"]
    text = "email me at x@y.co"
    start = text.index("x@")
    end = start + len("x@y.co")
    scorer = ContextualWordsScorer()
    ev = scorer.score_span_with_evidence(text, start, end, cfg, 50, 25)
    assert ev.score > 0.0
    assert "email" in [p.lower() for p in ev.matched_phrases]
    assert "email" in [p.lower() for p in ev.matched_in_before]


def test_classify_text_returns_pipeline_stage_result():
    sdk = SeibaScanner(verbose=False)
    res = sdk.classify_text("email me at x@y.co")
    assert res.stage == "deterministic+ner+contextual"
    assert res.text_length == len("email me at x@y.co")
    assert res.detections
    d0 = res.detections[0]
    assert d0.confidence_deterministic >= 0.0
    assert d0.confidence_contextual > 0.0
    assert d0.contextual_matches
    assert 0.3 <= d0.confidence <= 1.0


def test_classify_text_rescues_to_ssn_for_ssn_like_span():
    sdk = SeibaScanner(verbose=False)
    res = sdk.classify_text("SSN 987-65-4321")
    assert res.detections
    d0 = res.detections[0]
    assert d0.entity == "ssn"
    assert d0.rescue_applied is True
    assert d0.original_entity == "us_itin"


def test_classify_text_filters_low_fused_score():
    sdk = SeibaScanner(verbose=False)
    # Typical fused score for this line is well below 0.95
    res = sdk.classify_text(
        "email me at x@y.co",
        min_fused_confidence=0.95,
    )
    assert res.detections == []


def test_structured_key_boosts_contextual_score_for_email():
    sdk = SeibaScanner(verbose=False)
    res = sdk.classify_structured_text({"email": "x@y.co"})
    assert res.detections
    d0 = res.detections[0]
    assert d0.entity == "email_address"
    # Value alone has no "email" token, so this should come from the key.
    assert d0.contextual_matches_before is not None
    assert any(p.lower() == "email" for p in d0.contextual_matches_before)


def test_classify_structured_text_list_of_dicts_like_json_rows():
    """JSON/API-style list[dict] — same path as load_structured_json + classify_structured_text."""
    sdk = SeibaScanner(verbose=False)
    payload = [
        {"contact_email": "patient@clinic.example", "notes": "ok"},
        {"billing_email": "pay@hospital.example.org"},
    ]
    res = sdk.classify_structured_text(payload)
    assert res.stage == "deterministic+ner+contextual"
    emails = [d for d in res.detections if d.entity == "email_address"]
    assert len(emails) >= 2
    assert any(
        d.provenance and d.provenance.get("kind") == "list_of_dicts" for d in emails
    )


def test_bank_account_number_with_banking_keywords():
    sdk = SeibaScanner(verbose=False)
    res = sdk.classify_text("checking account 1234567890123 for deposit")
    # bank_account_number is its own Financial entity — not a kind of unique_identifier.
    assert any(d.entity_id == "fin_entity_ontology::bank_account_number" for d in res.detections)

