"""Shared helpers for eval.compare reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NER_SENSITIVE_SUFFIXES = frozenset(
    {
        "person_names",
        "physician_names",
        "city",
        "state",
        "street_address",
        "dates",
        "relative_date_expressions",
        "drivers_license_number",
        "hospital_names",
        "web_url",
    }
)


def load_report(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_report(arg: str, repo_root: Path) -> Path:
    """Run ID under eval/runs/, a directory with report.json, or a path to report.json."""
    p = Path(arg)
    if p.is_file():
        return p.resolve()
    if p.is_dir():
        return (p / "report.json").resolve()
    candidate = repo_root / "eval" / "runs" / arg
    if candidate.is_dir():
        return (candidate / "report.json").resolve()
    candidate_json = (repo_root / "eval" / "runs" / arg).with_suffix(".json")
    if candidate_json.is_file():
        return candidate_json.resolve()
    raise FileNotFoundError(f"Cannot resolve run: {arg!r}")


def backend_label(report: Dict[str, Any]) -> str:
    cfg = report.get("config") or {}
    backend = cfg.get("ner_backend", "spacy")
    model = cfg.get("ner_model")
    llm = cfg.get("llm_backend")
    label = f"{backend}" + (f" ({model})" if model else "")
    if llm:
        llm_model = cfg.get("llm_model", "")
        label += f" +llm:{llm}({llm_model})"
    return label


def ner_infer_total(report: Dict[str, Any]) -> float:
    timing = report.get("timing") or {}
    rows = timing.get("per_doc") or []
    total = 0.0
    for row in rows:
        st = row.get("stages") or {}
        total += float(st.get("ner_tokenize_infer_s", 0.0))
    return total


def wall_classify_total(report: Dict[str, Any]) -> float:
    timing = report.get("timing") or {}
    rows = timing.get("per_doc") or []
    return sum(float(row.get("wall_classify_s", 0.0)) for row in rows)


def ner_active(report: Dict[str, Any], *, skip_ner: bool = False) -> bool:
    if skip_ner:
        return False
    return ner_infer_total(report) > 0.0


def ner_active_from_report(report: Dict[str, Any]) -> bool:
    cfg = report.get("config") or {}
    return ner_active(report, skip_ner=bool(cfg.get("skip_ner")))


def llm_total(report: Dict[str, Any]) -> Optional[float]:
    timing = report.get("timing") or {}
    total = timing.get("llm_total_s")
    if total is not None:
        return float(total)
    rows = timing.get("per_doc") or []
    if not rows:
        return None
    summed = sum(float(row.get("llm_s", 0.0)) for row in rows)
    return summed if summed > 0 else None


def delta_str(a: float, b: float) -> str:
    d = a - b
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.3f}"


def per_entity_f1_deltas(
    report_a: Dict[str, Any],
    report_b: Dict[str, Any],
) -> List[Tuple[float, float, int, str, float, float]]:
    pe_a = report_a.get("per_entity") or {}
    pe_b = report_b.get("per_entity") or {}
    deltas = []
    for eid in sorted(set(pe_a.keys()) | set(pe_b.keys())):
        ra = pe_a.get(eid) or {}
        rb = pe_b.get(eid) or {}
        f1a = float(ra.get("f1", 0.0))
        f1b = float(rb.get("f1", 0.0))
        support = int(ra.get("support") or rb.get("support") or 0)
        deltas.append((abs(f1b - f1a), f1b - f1a, support, eid, f1a, f1b))
    deltas.sort(reverse=True)
    return deltas


def entity_suffix(entity_id: str) -> str:
    return entity_id.split("::")[-1] if "::" in entity_id else entity_id
