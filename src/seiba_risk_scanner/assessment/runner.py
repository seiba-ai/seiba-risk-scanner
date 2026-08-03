"""Scan data files and produce a readiness report — the SDK path from files to output.

    from seiba_risk_scanner.assessment import report_from_paths
    report = report_from_paths(["notes/", "patients.json"], out_dir="reports")

Text files (.txt/.md) are scanned as documents, one record each; tabular files (.json/.csv)
are scanned cell by cell, one record per row.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from seiba_risk_scanner.assessment.assessor import ReadinessAssessor
from seiba_risk_scanner.assessment.models import SensitiveDataReadinessReport
from seiba_risk_scanner.assessment.render import write_report
from seiba_risk_scanner.classification_engine.pipeline_models import PipelineStageResult
from seiba_risk_scanner.scanner import SeibaScanner

TEXT_SUFFIXES = frozenset({".txt", ".md"})
TABULAR_SUFFIXES = frozenset({".json", ".csv"})
PathLike = Union[str, Path]


def _expand(paths: Iterable[PathLike]) -> List[Path]:
    """Flatten directories into the data files they hold, keeping a stable order."""
    found: List[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found += sorted(
                p for p in path.rglob("*")
                if p.suffix.lower() in TEXT_SUFFIXES | TABULAR_SUFFIXES
            )
        elif path.suffix.lower() in TEXT_SUFFIXES | TABULAR_SUFFIXES:
            found.append(path)
    return found


def _rows(path: Path) -> List[Dict[str, Any]]:
    """Read a tabular file as a list of row dicts."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", errors="ignore", newline="") as handle:
            return list(csv.DictReader(handle))
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if isinstance(data, dict):
        return [data]
    return [row for row in data if isinstance(row, dict)]


def scan_paths(
    paths: Iterable[PathLike],
    scanner: Optional[SeibaScanner] = None,
    *,
    max_rows: Optional[int] = None,
) -> Tuple[List[PipelineStageResult], List[str]]:
    """Scan every supported file under ``paths``; returns results and their source labels."""
    scanner = scanner or SeibaScanner()
    files = _expand(paths)
    texts = [p for p in files if p.suffix.lower() in TEXT_SUFFIXES]
    tables = [p for p in files if p.suffix.lower() in TABULAR_SUFFIXES]

    # source_id is the full path so two same-named files in different folders stay
    # distinct; the label stays the basename, which is what a reader wants to see.
    results: List[PipelineStageResult] = []
    labels: List[str] = []
    if texts:
        results += scanner.classify_texts(
            [p.read_text(encoding="utf-8", errors="ignore") for p in texts],
            sources=[str(p) for p in texts],
        )
        labels += [p.name for p in texts]
    for table in tables:
        rows = _rows(table)
        results.append(
            scanner.classify_structured_text(
                rows[:max_rows] if max_rows else rows, source_id=str(table)
            )
        )
        labels.append(table.name)
    return results, labels


def report_from_paths(
    paths: Iterable[PathLike],
    *,
    scanner: Optional[SeibaScanner] = None,
    assessor: Optional[ReadinessAssessor] = None,
    health_context: Optional[bool] = None,
    max_rows: Optional[int] = None,
    out_dir: Optional[PathLike] = None,
    stem: str = "readiness_report",
    title: str = "Sensitive Data Report",
) -> SensitiveDataReadinessReport:
    """Scan ``paths``, assess them, and (when ``out_dir`` is set) write the JSON + Markdown."""
    results, labels = scan_paths(paths, scanner, max_rows=max_rows)
    if not results:
        raise ValueError(f"No .txt/.md/.json/.csv files found under: {list(paths)}")

    assessor = assessor or ReadinessAssessor()
    report = assessor.assess(results, labels=labels, health_context=health_context)
    if out_dir is not None:
        write_report(
            report,
            out_dir,
            stem,
            title=title,
            scope=f"{len(labels)} source(s): {', '.join(labels[:5])}"
            + (" …" if len(labels) > 5 else ""),
        )
    return report


__all__ = ["report_from_paths", "scan_paths", "TEXT_SUFFIXES", "TABULAR_SUFFIXES"]
