"""Scan one unstructured document and one table; write findings and a risk report."""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import (
    DATA,
    OUTPUT,
    TableScan,
    TextScan,
    add_backend_args,
    add_policy_args,
    optimize_from_args,
    scanner_from_args,
    throughput,
    timed_scan,
    warmup,
    write_findings,
    write_risk_report,
)

DEFAULT_TEXT = DATA / "notes/adv_01_neurology_consult.txt"
DEFAULT_TABLE = DATA / "tables/dirty_intake.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", type=Path, default=DEFAULT_TEXT)
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--max-rows", type=int, help="Cap rows per table.")
    add_backend_args(parser)
    add_policy_args(parser)
    args = parser.parse_args(argv)

    scanner = scanner_from_args(args)
    warmed = warmup(scanner)
    for job, source in (
        (TextScan(scanner), args.text),
        (TableScan(scanner, args.max_rows), args.table),
    ):
        results, labels, elapsed = timed_scan(job, source)
        timing = throughput(results, labels, elapsed, warmed)
        findings = write_findings(results, labels, source.stem, args.out / "single", timing)
        report = write_risk_report(
            results,
            labels,
            f"{source.stem}_risk",
            optimize=optimize_from_args(args),
            out_dir=args.out / "reports",
        )
        print(
            f"{source.name}: {sum(len(r.detections) for r in results)} findings "
            f"in {timing['scan_s']}s ({timing['records_per_s']} records/s)"
        )
        print(f"  findings -> {findings}")
        print(f"  report   -> {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
