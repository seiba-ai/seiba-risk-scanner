"""Gold loading and eval types."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
for _p in (repo_root / "src", repo_root):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from eval.gold import load_gold_jsonl  # noqa: E402
from eval.runner import run_eval  # noqa: E402
from seiba_risk_scanner.config import EvalConfig, ScannerConfig  # noqa: E402


def test_gold_spans_carry_source_file():
    gold_path = repo_root / "eval" / "ground_truth" / "unstructured_v2" / "phi_restricted_clinical_notes.gold.jsonl"
    gdoc = load_gold_jsonl(gold_path, repo_root=repo_root)
    assert gdoc.source_file == "phi_restricted_clinical_notes.txt"
    assert gdoc.spans
    for s in gdoc.spans:
        assert s.source_file == "phi_restricted_clinical_notes.txt"


@pytest.mark.slow
def test_run_eval_includes_timing_and_full_fp_fn_lists():
    """Per-document mode keeps the per-stage timing breakdown."""
    gold_dir = repo_root / "eval" / "ground_truth" / "unstructured_v2"
    out = run_eval(
        repo_root=repo_root,
        eval_config=EvalConfig(
            gold_dir=gold_dir, min_fused_confidence=0.3, warmup=False, batched=False
        ),
        scanner_config=ScannerConfig(skip_ner=False),
    )
    assert "timing" in out["report"]
    assert out["report"]["timing"]["per_doc"]
    assert len(out["report"]["timing"]["per_doc"]) >= 3
    assert "wall_classify_s" in out["report"]["timing"]["per_doc"][0]
    stages = out["report"]["timing"]["per_doc"][0].get("stages") or {}
    assert "load_entity_configs_s" in stages
    assert isinstance(out["all_fp"], list)
    assert isinstance(out["all_fn"], list)
    assert isinstance(out["all_pred"], list)
    assert len(out["all_pred"]) >= len(out["all_fp"])


@pytest.mark.slow
def test_batched_eval_matches_per_doc_predictions():
    """Batching shares one NER forward pass; it must not change a single span."""
    gold_dir = repo_root / "eval" / "ground_truth" / "unstructured_v2"

    def run(batched: bool):
        return run_eval(
            repo_root=repo_root,
            eval_config=EvalConfig(
                gold_dir=gold_dir, min_fused_confidence=0.3, warmup=False, batched=batched
            ),
            scanner_config=ScannerConfig(skip_ner=False),
        )

    def spans(out):
        return sorted(
            (p.provenance.get("doc", ""), p.start, p.end, p.entity_id) for p in out["all_pred"]
        )

    batched_out = run(True)
    assert spans(batched_out) == spans(run(False))

    timing = batched_out["report"]["timing"]
    assert timing["batched"] is True
    assert timing["batch_wall_s"] > 0
    assert timing["per_doc"] == []
