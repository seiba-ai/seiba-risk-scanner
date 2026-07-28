"""Shared batch-eval loop for NER / LLM comparison runners."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass
class BatchJob:
    """One eval configuration to run."""

    key: str
    label: str
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchJobResult:
    key: str
    label: str
    status: str  # ok | failed | skipped
    config: Dict[str, Any]
    error: Optional[str] = None
    report: Optional[Dict[str, Any]] = None
    report_path: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def run_batch_jobs(
    jobs: Sequence[BatchJob],
    *,
    run_one: Callable[[BatchJob], BatchJobResult],
    dry_run: bool = False,
) -> List[BatchJobResult]:
    """Iterate jobs, call run_one, catch failures as status=failed."""
    print(f"Batch: {len(jobs)} job(s) to run.")
    if dry_run:
        print("[dry-run] Configurations that would run:")
        for index, job in enumerate(jobs, 1):
            print(f"  {index}. {job.label}")
        return []

    results: List[BatchJobResult] = []
    for index, job in enumerate(jobs, 1):
        print(f"\n[{index}/{len(jobs)}] {job.label}")
        try:
            result = run_one(job)
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR: {exc}")
            result = BatchJobResult(
                key=job.key,
                label=job.label,
                status="failed",
                config=dict(job.config),
                error=repr(exc),
            )
        results.append(result)
    return results
