"""Quantified regression gate against a checked-in baseline.

This is intentionally separate from unit tests: it asserts quality doesn't regress
on the gold-annotated unstructured eval set.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

repo_root_for_import = Path(__file__).resolve().parents[1]
for _p in (repo_root_for_import / "src", repo_root_for_import):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from eval.runner import run_eval  # noqa: E402
from seiba_risk_scanner.config import EvalConfig, ScannerConfig  # noqa: E402


TOL_MICRO_F1 = 0.01
TOL_ENTITY_F1 = 0.05
ENTITY_SUPPORT_MIN = 3


@pytest.mark.slow
def test_unstructured_eval_does_not_regress_vs_baseline():
    repo_root = Path(__file__).resolve().parents[1]
    baseline_path = repo_root / "eval" / "baselines" / "unstructured_baseline.json"
    gold_dir = repo_root / "eval" / "ground_truth" / "unstructured_v2"

    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    base_micro_f1 = float(baseline["headline"]["micro"]["f1"])
    base_per_entity = baseline.get("per_entity", {}) or {}

    out = run_eval(
        repo_root=repo_root,
        eval_config=EvalConfig(
            gold_dir=gold_dir,
            min_fused_confidence=float(baseline["config"]["min_fused_confidence"]),
        ),
        # Reproduce the run the baseline recorded rather than whatever the defaults are
        # today, so a default change cannot silently compare two different pipelines.
        scanner_config=ScannerConfig(
            skip_ner=bool(baseline["config"]["skip_ner"]),
            ner_backend=baseline["config"]["ner_backend"],
        ),
    )

    micro = out["report"]["headline"]["micro"]
    micro_f1 = float(micro["f1"])

    assert micro_f1 + TOL_MICRO_F1 >= base_micro_f1, (
        f"Micro F1 regressed: {micro_f1:.3f} vs baseline {base_micro_f1:.3f} "
        f"(tol={TOL_MICRO_F1:.3f})"
    )

    # Per-entity gate: only for entities with support >= ENTITY_SUPPORT_MIN in the baseline.
    per_entity_now = out["report"].get("per_entity", {}) or {}
    for eid, base in base_per_entity.items():
        support = int(base.get("support", 0) or 0)
        if support < ENTITY_SUPPORT_MIN:
            continue
        base_f1 = float(base.get("f1", 0.0))
        now_f1 = float((per_entity_now.get(eid, {}) or {}).get("f1", 0.0))
        assert now_f1 + TOL_ENTITY_F1 >= base_f1, (
            f"Entity F1 regressed for {eid}: {now_f1:.3f} vs baseline {base_f1:.3f} "
            f"(support={support}, tol={TOL_ENTITY_F1:.3f})"
        )

