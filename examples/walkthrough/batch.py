"""Batch-scan the unstructured and structured corpora into one findings file and one risk report."""

from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

from seiba_risk_scanner import SeibaScanner

from .core import (
    DATA,
    OUTPUT,
    TableScan,
    TextScan,
    add_backend_args,
    scanner_from_args,
    throughput,
    warmup,
    write_findings,
    write_risk_report,
)

DEFAULT_NOTES = DATA / "notes"
DEFAULT_TABLES = DATA / "tables"


def scan_unstructured(scanner: SeibaScanner, source: Path = DEFAULT_NOTES):
    return TextScan(scanner).scan(source)


def scan_structured(scanner: SeibaScanner, source: Path = DEFAULT_TABLES, max_rows: int | None = None):
    return TableScan(scanner, max_rows).scan(source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("--tables", type=Path, default=DEFAULT_TABLES)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--stem", default="corpus")
    parser.add_argument("--optimize", action="store_true", help="Run the action optimizer.")
    parser.add_argument("--max-rows", type=int, help="Cap rows per table.")
    add_backend_args(parser)
    args = parser.parse_args(argv)

    scanner = scanner_from_args(args)
    warmed = warmup(scanner)
    started = perf_counter()
    text_results, text_labels = scan_unstructured(scanner, args.notes)
    table_results, table_labels = scan_structured(scanner, args.tables, args.max_rows)
    elapsed = perf_counter() - started

    results, labels = text_results + table_results, text_labels + table_labels
    timing = throughput(results, labels, elapsed, warmed)
    findings = write_findings(results, labels, args.stem, args.out / "batch", timing)
    report = write_risk_report(
        results, labels, f"{args.stem}_risk", args.optimize, args.out / "reports"
    )

    print(
        f"{len(labels)} sources, {sum(len(r.detections) for r in results)} findings "
        f"in {timing['scan_s']}s ({timing['records_per_s']} records/s, "
        f"warmup {timing['warmup_s']}s excluded)"
    )
    print(f"  findings -> {findings}")
    print(f"  report   -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
