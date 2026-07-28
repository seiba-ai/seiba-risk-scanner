"""LLM stage tests — no live LLM required (backend override via mock)."""

from __future__ import annotations

import seiba_risk_scanner.classification_engine.llm.llm_runner as llm_mod
from seiba_risk_scanner.classification_engine.llm.llm_runner import (
    BACKENDS,
    LLMSpanRecord,
    _gap_entity_ids,
    _iter_chunks,
    _load_hints,
)
from seiba_risk_scanner.classification_engine.pipeline_models import CombinedDetectionRow
from seiba_risk_scanner import SeibaScanner


def test_llm_params_accepted():
    sdk = SeibaScanner(
        skip_ner=True,
        llm_backend="ollama",
        llm_model="qwen2.5:3b",
        llm_base_url="http://localhost:11434",
        llm_coverage="gaps",
        llm_skip_if_above=0.85,
    )
    assert sdk.llm_backend == "ollama"
    assert sdk.llm_model == "qwen2.5:3b"
    assert sdk.llm_coverage == "gaps"
    assert sdk.llm_skip_if_above == 0.85


def test_llm_disabled_by_default():
    sdk = SeibaScanner(skip_ner=True)
    assert sdk.llm_backend is None
    assert sdk.llm_model is None


def test_confidence_llm_field_on_detection():
    sdk = SeibaScanner(skip_ner=True)
    res = sdk.classify_text("SSN 123-45-6789")
    assert res.detections
    assert res.detections[0].confidence_llm is None


def test_llm_stage_skipped_when_backend_none(monkeypatch):
    calls = []

    monkeypatch.setattr(llm_mod, "run_llm_gap_fill", lambda *a, **kw: calls.append(1) or [])

    sdk = SeibaScanner(skip_ner=True)
    sdk.classify_text("jane@example.com")
    assert not calls, "run_llm_gap_fill should not be called when llm_backend is None"


def test_llm_span_merged_into_detections(monkeypatch):
    """Mock LLM returns a person_name span; verify it appears in final detections."""
    fake_span = LLMSpanRecord(
        start=11, end=21, text="John Smith",
        entity_id="pii_entity_ontology::person_names",
        confidence_llm=0.75, pipeline="ollama",
    )
    monkeypatch.setattr(llm_mod, "run_llm_gap_fill", lambda *a, **kw: [fake_span])

    sdk = SeibaScanner(skip_ner=True, llm_backend="ollama", llm_model="qwen2.5:3b")
    res = sdk.classify_text("Patient: John Smith visited today.")

    llm_dets = [d for d in res.detections if d.winner_kind == "llm"]
    assert llm_dets, "Expected at least one LLM detection"
    assert llm_dets[0].entity == "person_names"
    assert llm_dets[0].confidence_llm == 0.75
    assert llm_dets[0].text == "John Smith"


def test_gap_entity_ids_gaps_coverage():
    hints = _load_hints()
    gaps = _gap_entity_ids([], hints, skip_if_above=0.85, coverage="gaps")
    assert "pii_entity_ontology::person_names" in gaps
    assert "pii_entity_ontology::city" in gaps


def test_gap_entity_ids_skips_high_confidence():
    hints = {"pii_entity_ontology::person_names": {}, "pii_entity_ontology::city": {}}
    existing = [
        CombinedDetectionRow(
            winner_kind="ner",
            entity_id="pii_entity_ontology::person_names",
            entity="person_names",
            start=0, end=10, text="John Smith",
            confidence=0.90,
            confidence_deterministic=0.0,
            confidence_contextual=0.0,
        )
    ]
    gaps = _gap_entity_ids(existing, hints, skip_if_above=0.85, coverage="gaps")
    assert "pii_entity_ontology::person_names" not in gaps
    assert "pii_entity_ontology::city" in gaps


def test_gap_entity_ids_full_coverage():
    hints = {"pii_entity_ontology::person_names": {}, "pii_entity_ontology::city": {}}
    existing = [
        CombinedDetectionRow(
            winner_kind="ner",
            entity_id="pii_entity_ontology::person_names",
            entity="person_names",
            start=0, end=10, text="John Smith",
            confidence=0.90,
            confidence_deterministic=0.0,
            confidence_contextual=0.0,
        )
    ]
    gaps = _gap_entity_ids(existing, hints, skip_if_above=0.85, coverage="full")
    assert "pii_entity_ontology::person_names" in gaps
    assert "pii_entity_ontology::city" in gaps


def test_iter_chunks_short_text():
    chunks = _iter_chunks("hello world")
    assert len(chunks) == 1
    assert chunks[0] == ("hello world", 0)


def test_iter_chunks_long_text():
    text = "x" * 10_000
    chunks = _iter_chunks(text)
    assert len(chunks) > 1
    for chunk, offset in chunks:
        assert offset >= 0
        assert offset + len(chunk) <= len(text)
    assert chunks[0][1] == 0
    last_chunk, last_offset = chunks[-1]
    assert last_offset + len(last_chunk) == len(text)


def test_hints_loaded():
    hints = _load_hints()
    assert hints
    assert "pii_entity_ontology::person_names" in hints
    assert "phi_entity_ontology::physician_names" in hints
    assert "fin_entity_ontology::bank_account_number" in hints


def test_transformers_backend_in_backends_list():
    assert "transformers" in BACKENDS


def test_llm_backend_sets_default_model():
    sdk = SeibaScanner(skip_ner=True, llm_backend="transformers")
    assert sdk.llm_backend == "transformers"
    assert sdk.llm_model == "Qwen/Qwen2.5-3B-Instruct"


def test_llm_backend_respects_model_override():
    sdk = SeibaScanner(
        skip_ner=True,
        llm_backend="ollama",
        llm_model="qwen2.5:7b",
    )
    assert sdk.llm_backend == "ollama"
    assert sdk.llm_model == "qwen2.5:7b"


def test_transformers_backend_accepted_by_scanner():
    sdk = SeibaScanner(
        skip_ner=True,
        llm_backend="transformers",
        llm_model="Qwen/Qwen2.5-3B-Instruct",
    )
    assert sdk.llm_backend == "transformers"
    assert sdk.llm_model == "Qwen/Qwen2.5-3B-Instruct"


def test_transformers_backend_calls_gap_fill(monkeypatch):
    """Monkeypatched stub confirms LLM stage is invoked — no real model loaded."""
    calls = []
    monkeypatch.setattr(llm_mod, "run_llm_gap_fill", lambda *a, **kw: calls.append(1) or [])
    sdk = SeibaScanner(skip_ner=True, llm_backend="transformers", llm_model="Qwen/Qwen2.5-3B-Instruct")
    sdk.classify_text("Patient Alice Brown visited clinic.")
    assert calls, "run_llm_gap_fill should be called when llm_backend is set"


def test_invalid_llm_coverage_raises():
    from pydantic import ValidationError

    try:
        SeibaScanner(skip_ner=True, llm_backend="ollama", llm_coverage="gap_fill")
        assert False, "expected ValidationError"
    except (ValueError, ValidationError) as exc:
        assert "llm_coverage" in str(exc) or "gaps" in str(exc) or "full" in str(exc)
