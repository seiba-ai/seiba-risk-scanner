"""Optional demo: show the regression gate would catch a deliberate degradation.

This test is skipped by default. Enable with:
  RUN_EVAL_DEMO=1 pytest -q tests/test_eval_regression_demo_optional.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

repo_root_for_import = Path(__file__).resolve().parents[1]
for _p in (repo_root_for_import / "src", repo_root_for_import):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from eval.runner import run_eval  # noqa: E402
from seiba_risk_scanner.config import EvalConfig, ScannerConfig  # noqa: E402


@pytest.mark.skipif(os.environ.get("RUN_EVAL_DEMO") != "1", reason="Set RUN_EVAL_DEMO=1 to run")
def test_demo_regression_gate_would_fail_on_bad_threshold():
    repo_root = Path(__file__).resolve().parents[1]
    baseline_path = repo_root / "eval" / "baselines" / "unstructured_baseline.json"
    gold_dir = repo_root / "eval" / "ground_truth" / "unstructured_v2"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    base_micro_f1 = float(baseline["headline"]["micro"]["f1"])

    # Deliberately degrade recall by setting a very high threshold.
    out = run_eval(
        repo_root=repo_root,
        eval_config=EvalConfig(gold_dir=gold_dir, min_fused_confidence=0.95),
        scanner_config=ScannerConfig(skip_ner=bool(baseline["config"]["skip_ner"])),
    )

    micro_f1 = float(out["report"]["headline"]["micro"]["f1"])
    assert micro_f1 < base_micro_f1, "Expected deliberate regression did not reduce micro F1"

