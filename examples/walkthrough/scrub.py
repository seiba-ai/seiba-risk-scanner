"""Write de-identified copies of the corpora, keyed by their source file names."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from seiba_risk_scanner import SeibaScanner
from seiba_risk_scanner.assessment import ReadinessAssessor
from seiba_risk_scanner.policy import scrub_rows, scrub_text

from .core import DATA, OUTPUT, add_backend_args, scanner_from_args

DEFAULT_NOTES = DATA / "notes"
DEFAULT_TABLES = DATA / "tables"


def collect(source: Path, suffix: str) -> list[Path]:
    return sorted(source.rglob(f"*{suffix}")) if source.is_dir() else [source]


def load(path: Path, max_rows: int | None = None):
    """A table becomes a list of row dicts; anything else is read as one string."""
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))[:max_rows]
    return path.read_text(encoding="utf-8")


def scan_one(scanner: SeibaScanner, path: Path, data):
    if isinstance(data, str):
        return scanner.classify_text(data, source_id=str(path), source_label=path.name)
    return scanner.classify_structured_text(data, source_id=str(path), source_label=path.name)


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
        return path
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows(data)
    return path


def scrub_corpus(scanner: SeibaScanner, paths: list[Path], out_dir: Path, max_rows=None) -> dict:
    sources = {str(path): load(path, max_rows) for path in paths}
    results = [scan_one(scanner, path, sources[str(path)]) for path in paths]
    labels = [path.name for path in paths]

    report = ReadinessAssessor().assess(results, labels=labels, health_context=True)
    records = report.policy_plan.records

    summary = []
    for path, result in zip(paths, results):
        data = sources[str(path)]
        entry = {"source": path.name, "findings": len(result.detections)}
        scrub = scrub_text if isinstance(data, str) else scrub_rows
        try:
            entry["output"] = str(write(out_dir / path.name, scrub(data, records, str(path))))
        except ValueError as exc:
            # Left unwritten on purpose: a partially scrubbed file would look de-identified.
            entry["error"] = str(exc)
        summary.append(entry)
    return {
        "sources": len(paths),
        "written": sum(1 for row in summary if "output" in row),
        "findings": sum(row["findings"] for row in summary),
        "files": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("--tables", type=Path, default=DEFAULT_TABLES)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--max-rows", type=int, help="Cap rows per table.")
    add_backend_args(parser)
    args = parser.parse_args(argv)

    paths = collect(args.notes, ".txt") + collect(args.tables, ".csv")
    out_dir = args.out / "scrubbed"
    summary = scrub_corpus(scanner_from_args(args), paths, out_dir, args.max_rows)
    (out_dir / "scrub_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(
        f"{summary['written']}/{summary['sources']} sources scrubbed -> {out_dir}"
    )
    for row in summary["files"]:
        status = row.get("error", f"{row['findings']} replaced")
        print(f"  {row['source']:38} {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
