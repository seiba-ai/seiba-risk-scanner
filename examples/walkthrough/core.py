from __future__ import annotations

import csv
import json
from pathlib import Path
from time import perf_counter

from seiba_risk_scanner import ScannerConfig, SeibaScanner
from seiba_risk_scanner.assessment import ReadinessAssessor, write_report

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUTPUT = ROOT / "outputs"


def build_scanner(
    ner_backend: str = "openmed",
    ner_model: str | None = None,
    llm_backend: str | None = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
) -> SeibaScanner:
    """Scanner on the bundled NER backend, optionally with an LLM gap-filling stage."""
    return SeibaScanner(
        config=ScannerConfig(
            ner_backend=ner_backend,
            ner_model=ner_model,
            llm_backend=llm_backend,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
        )
    )


class ScanJob:
    """Scans one kind of source into pipeline results plus their source labels."""

    suffix = ""

    def __init__(self, scanner: SeibaScanner):
        self.scanner = scanner

    def resolve(self, source: Path) -> list[Path]:
        if source.is_dir():
            return sorted(source.rglob(f"*{self.suffix}"))
        return [source]

    def scan(self, source: Path):
        raise NotImplementedError


class TextScan(ScanJob):
    suffix = ".txt"

    def scan(self, source: Path):
        paths = self.resolve(source)
        texts = [path.read_text(encoding="utf-8") for path in paths]
        # source ids let the policy plan route each replacement back to its own file.
        results = self.scanner.classify_texts(texts, sources=[str(p) for p in paths])
        return results, [path.name for path in paths]


class TableScan(ScanJob):
    """One result per table; each cell keeps its row and column key."""

    suffix = ".csv"

    def __init__(self, scanner: SeibaScanner, max_rows: int | None = None):
        super().__init__(scanner)
        self.max_rows = max_rows

    def scan(self, source: Path):
        results, labels = [], []
        for path in self.resolve(source):
            with path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            results.append(
                self.scanner.classify_structured_text(
                    rows[: self.max_rows], source_id=str(path), source_label=path.name
                )
            )
            labels.append(path.name)
        return results, labels


def add_backend_args(parser) -> None:
    parser.add_argument("--ner-backend", default="openmed", choices=["openmed", "spacy"])
    parser.add_argument("--ner-model")
    parser.add_argument("--llm-backend", choices=["openai", "transformers", "ollama", "llama_cpp", "vllm"])
    parser.add_argument("--llm-model")
    parser.add_argument("--llm-base-url")


def scanner_from_args(args) -> SeibaScanner:
    return build_scanner(
        args.ner_backend, args.ner_model, args.llm_backend, args.llm_model, args.llm_base_url
    )


def warmup(scanner: SeibaScanner) -> float:
    """Models load on the first scan; time that separately or throughput is wrong."""
    started = perf_counter()
    scanner.classify_text("warmup")
    return perf_counter() - started


def timed_scan(job: ScanJob, source: Path):
    started = perf_counter()
    results, labels = job.scan(source)
    return results, labels, perf_counter() - started


def record_count(results) -> int:
    """Records the assessor will build: a structured row, else the whole document."""
    return len(
        {
            (index, (row.provenance or {}).get("row"))
            for index, result in enumerate(results)
            for row in result.detections
        }
    )


def throughput(results, labels, seconds: float, warmup_s: float = 0.0) -> dict:
    characters = sum(result.text_length for result in results)
    findings = sum(len(result.detections) for result in results)
    return {
        "warmup_s": round(warmup_s, 2),
        "scan_s": round(seconds, 2),
        "sources_per_s": round(len(labels) / seconds, 2) if seconds else 0.0,
        "records_per_s": round(record_count(results) / seconds, 2) if seconds else 0.0,
        "chars_per_s": round(characters / seconds) if seconds else 0,
        "findings_per_s": round(findings / seconds, 1) if seconds else 0.0,
    }


def write_findings(results, labels, stem: str, out_dir: Path = OUTPUT, timing: dict | None = None) -> Path:
    """Write raw scan results — every detection with confidence and provenance."""
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "sources": len(labels),
        "total_findings": sum(len(result.detections) for result in results),
        "timing": timing or {},
        "results": [
            {"source": label, **result.model_dump(mode="json")}
            for label, result in zip(labels, results)
        ],
    }
    path = out_dir / f"{stem}_findings.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_risk_report(
    results, labels, stem: str, optimize: bool = False, out_dir: Path = OUTPUT
) -> Path:
    """Assess severity and exposure, then write the Markdown report and its JSON companion."""
    report = ReadinessAssessor(optimize=optimize).assess(
        results, labels=labels, health_context=True
    )
    _, markdown = write_report(
        report,
        out_dir,
        stem,
        title="Sensitive Data Risk Report",
        scope=f"{len(labels)} source(s): {', '.join(labels[:5])}"
        + (" …" if len(labels) > 5 else ""),
    )
    return markdown
