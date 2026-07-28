"""LLM comparison batch runner."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from eval.batch import BatchJob, BatchJobResult, run_batch_jobs
from eval.compare_common import llm_total, ner_infer_total
from eval.discovery import resolve_gold_dir
from eval.report import write_json
from eval.runner import run_eval
from eval.util import bootstrap_repo_paths
from seiba_risk_scanner.config import EvalConfig, ScannerConfig

_repo_root = Path(__file__).resolve().parents[2]
bootstrap_repo_paths(_repo_root)


def _build_combos(
    ner_backends: List[str],
    llm_backend: Optional[str],
    llm_models: List[str],
    llm_coverages: List[str],
    include_no_llm: bool,
) -> List[Dict[str, Any]]:
    """Cartesian product of NER × LLM model × LLM coverage, plus no-LLM baselines."""
    combos: List[Dict[str, Any]] = []
    for ner in ner_backends:
        if include_no_llm:
            combos.append(
                {"ner_backend": ner, "llm_backend": None, "llm_model": None, "llm_coverage": "gaps"}
            )
        if llm_backend:
            for model in llm_models:
                for coverage in llm_coverages:
                    combos.append(
                        {
                            "ner_backend": ner,
                            "llm_backend": llm_backend,
                            "llm_model": model,
                            "llm_coverage": coverage,
                        }
                    )
    return combos


def _fmt(x: float) -> str:
    return f"{x:.3f}"


def _fmt_s(x: Optional[float]) -> str:
    if x is None:
        return "—"
    return f"{x:.2f}s"


def _print_comparison_table(rows: List[Dict[str, Any]]) -> None:
    """Print a markdown-style comparison table to stdout."""
    headers = ["NER", "LLM", "model", "coverage", "micro_F1", "P", "R", "NER_s", "LLM_s", "net_gain"]
    col_w = [max(len(h), 8) for h in headers]

    def _pad(s: str, w: int) -> str:
        return s.ljust(w)

    print()
    print("## LLM comparison matrix")
    print()
    header_line = " | ".join(_pad(h, col_w[i]) for i, h in enumerate(headers))
    print("| " + header_line + " |")
    print("|-" + "-|-".join("-" * w for w in col_w) + "-|")
    for row in rows:
        cfg = row["config"]
        micro = row["micro"]
        attr = row.get("llm_attribution") or {}
        cells = [
            cfg.get("ner_backend", "spacy"),
            cfg.get("llm_backend") or "none",
            (cfg.get("llm_model") or "—")[:20],
            cfg.get("llm_coverage") or "—",
            _fmt(micro["f1"]),
            _fmt(micro["precision"]),
            _fmt(micro["recall"]),
            _fmt_s(row.get("ner_infer_s")),
            _fmt_s(row.get("llm_total_s")),
            f"{attr.get('llm_net_f1_gain', 0.0):+.3f}" if attr else "—",
        ]
        row_line = " | ".join(_pad(c, col_w[i]) for i, c in enumerate(cells))
        print("| " + row_line + " |")
    print()


def run_batch(
    *,
    repo_root: Path,
    gold_dir: Path,
    ner_backends: List[str],
    llm_backend: Optional[str],
    llm_models: List[str],
    llm_coverages: List[str],
    llm_base_url: Optional[str],
    llm_skip_if_above: float,
    min_fused_confidence: float,
    skip_ner: bool,
    out_dir: Path,
    dry_run: bool = False,
) -> List[Dict[str, Any]]:
    combos = _build_combos(
        ner_backends=ner_backends,
        llm_backend=llm_backend,
        llm_models=llm_models,
        llm_coverages=llm_coverages,
        include_no_llm=True,
    )

    jobs: List[BatchJob] = []
    for combo in combos:
        ner = combo["ner_backend"]
        llm = combo["llm_backend"]
        model = combo["llm_model"]
        coverage = combo["llm_coverage"]
        key = f"{ner}" + (
            f"-{llm}-{(model or '').replace(':', '_')}-{coverage}" if llm else "-no_llm"
        )
        label = f"ner={ner}" + (f" llm={llm}:{model}:{coverage}" if llm else " (no LLM)")
        jobs.append(BatchJob(key=key, label=label, config=combo))

    if dry_run:
        return run_batch_jobs(jobs, run_one=lambda job: BatchJobResult(
            key=job.key, label=job.label, status="skipped", config=job.config
        ), dry_run=True)

    out_dir.mkdir(parents=True, exist_ok=True)

    def run_one(job: BatchJob) -> BatchJobResult:
        combo = job.config
        out = run_eval(
            repo_root=repo_root,
            eval_config=EvalConfig(
                gold_dir=gold_dir,
                min_fused_confidence=min_fused_confidence,
                warmup=False,
            ),
            scanner_config=ScannerConfig(
                skip_ner=skip_ner,
                ner_backend=combo["ner_backend"],
                llm_backend=combo["llm_backend"],
                llm_model=combo["llm_model"],
                llm_base_url=llm_base_url,
                llm_coverage=combo["llm_coverage"],
                llm_skip_if_above=llm_skip_if_above,
            ),
        )
        report = out["report"]
        micro = report["headline"]["micro"]
        llm_attr = report.get("llm_attribution")
        ner_infer_s = ner_infer_total(report)
        llm_total_s = llm_total(report)
        write_json(out_dir / f"{job.key}.json", report)
        print(
            f"  micro_F1={micro['f1']:.3f}  P={micro['precision']:.3f}  R={micro['recall']:.3f}"
            + (f"  llm_net_gain={llm_attr['llm_net_f1_gain']:+.3f}" if llm_attr else "")
        )
        return BatchJobResult(
            key=job.key,
            label=job.label,
            status="ok",
            config=dict(combo),
            report=report,
            report_path=str(out_dir / f"{job.key}.json"),
            extra={
                "micro": micro,
                "ner_infer_s": ner_infer_s if ner_infer_s > 0 else None,
                "llm_total_s": llm_total_s,
                "llm_attribution": llm_attr,
            },
        )

    job_results = run_batch_jobs(jobs, run_one=run_one)
    results: List[Dict[str, Any]] = []
    for result in job_results:
        if result.status != "ok" or not result.report:
            continue
        results.append(
            {
                "config": result.config,
                "micro": result.extra["micro"],
                "ner_infer_s": result.extra.get("ner_infer_s"),
                "llm_total_s": result.extra.get("llm_total_s"),
                "llm_attribution": result.extra.get("llm_attribution"),
            }
        )

    write_json(out_dir / "matrix.json", results)
    _print_comparison_table(results)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM comparison batch eval runner.")
    ap.add_argument("--gold-dir", default=None)
    ap.add_argument("--ner-backends", default="spacy", help="Comma-separated NER backends.")
    ap.add_argument(
        "--llm-backend",
        default="transformers",
        choices=("transformers", "ollama", "llama_cpp", "vllm"),
        help="LLM backend (default: transformers).",
    )
    ap.add_argument(
        "--llm-models",
        default="Qwen/Qwen2.5-3B-Instruct",
        help="Comma-separated HF model IDs or names (default: Qwen/Qwen2.5-3B-Instruct).",
    )
    ap.add_argument("--llm-coverages", default="gaps", help="Comma-separated coverages: gaps,full.")
    ap.add_argument("--llm-base-url", default=None)
    ap.add_argument("--llm-skip-if-above", type=float, default=0.85)
    ap.add_argument("--min-fused-confidence", type=float, default=0.3)
    ap.add_argument("--skip-ner", action="store_true", default=False)
    ap.add_argument("--out-dir", default=None, help="Output directory for results.")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print configs that would run, then exit without running eval.",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    gold_dir = resolve_gold_dir(repo_root, gold_dir_arg=args.gold_dir)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir) if args.out_dir else repo_root / "eval" / "runs" / f"{ts}-llm_batch"

    ner_backends = [b.strip() for b in args.ner_backends.split(",") if b.strip()]
    llm_models = [m.strip() for m in args.llm_models.split(",") if m.strip()]
    llm_coverages = [m.strip() for m in args.llm_coverages.split(",") if m.strip()]

    run_batch(
        repo_root=repo_root,
        gold_dir=gold_dir,
        ner_backends=ner_backends,
        llm_backend=args.llm_backend,
        llm_models=llm_models,
        llm_coverages=llm_coverages,
        llm_base_url=args.llm_base_url,
        llm_skip_if_above=args.llm_skip_if_above,
        min_fused_confidence=args.min_fused_confidence,
        skip_ner=args.skip_ner,
        out_dir=out_dir,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
