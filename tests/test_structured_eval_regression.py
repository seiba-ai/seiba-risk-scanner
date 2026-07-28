"""Quantified regression gate for structured (JSON-rows) scanning.

Mirrors test_eval_regression.py. Tabular scanning is the side of the product OpenMed
does not cover, so it gets the same protection as prose: without a gate it can rot
silently while the unstructured numbers stay green.
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

from eval.structured_runner import BASELINE_PATH, build_baseline  # noqa: E402


TOL_MICRO_F1 = 0.01
TOL_ENTITY_F1 = 0.05
ENTITY_SUPPORT_MIN = 3


@pytest.mark.slow
def test_structured_eval_does_not_regress_vs_baseline():
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    now = build_baseline(baseline["config"]["ner_backend"])

    base_f1 = float(baseline["headline"]["micro"]["f1"])
    now_f1 = float(now["headline"]["micro"]["f1"])
    assert now_f1 + TOL_MICRO_F1 >= base_f1, (
        f"Structured micro F1 regressed: {now_f1:.3f} vs baseline {base_f1:.3f} "
        f"(tol={TOL_MICRO_F1:.3f})"
    )

    per_entity_now = now.get("per_entity", {}) or {}
    for eid, base in (baseline.get("per_entity", {}) or {}).items():
        support = int(base.get("support", 0) or 0)
        if support < ENTITY_SUPPORT_MIN:
            continue
        base_entity_f1 = float(base.get("f1", 0.0))
        now_entity_f1 = float((per_entity_now.get(eid, {}) or {}).get("f1", 0.0))
        assert now_entity_f1 + TOL_ENTITY_F1 >= base_entity_f1, (
            f"Structured entity F1 regressed for {eid}: {now_entity_f1:.3f} vs "
            f"baseline {base_entity_f1:.3f} (support={support}, tol={TOL_ENTITY_F1:.3f})"
        )
