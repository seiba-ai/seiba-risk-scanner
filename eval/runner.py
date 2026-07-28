from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

_repo_root = Path(__file__).resolve().parents[1]

from eval.discovery import discover_gold_files, resolve_gold_dir
from eval.gold import load_gold_jsonl
from eval.metrics import (
    llm_attribution_metrics,
    micro_from_entity_metrics,
    rescue_diagnostics,
    winner_kind_breakdown,
)
from eval.predictors import SeibaScannerPredictor
from eval.report import (
    ReportContext,
    build_false_negatives_md,
    build_false_positives_md,
    build_report_dict,
    build_report_md,
    build_rescues_md,
    predspan_to_json_obj,
    write_json,
)
from eval.scoring import score_predictions
from eval.types import GoldSpan, PredSpan
from eval.util import (
    bootstrap_repo_paths,
    ensure_dir,
    git_sha,
    ms_per_1k_chars,
    now_run_id,
)
from seiba_risk_scanner.config import (
    DEFAULT_FUSION_WEIGHT_CONTEXTUAL,
    DEFAULT_FUSION_WEIGHT_DETERMINISTIC,
    DEFAULT_MIN_FUSED_CONFIDENCE,
    EvalConfig,
    ScannerConfig,
)

bootstrap_repo_paths(_repo_root)

def write_eval_artifacts(
    out_dir: Path,
    run_id: str,
    out: Dict[str, Any],
    report: Dict[str, Any],
) -> None:
    ensure_dir(out_dir)

    artifact_names = {
        "False positives (full)": "false_positives.md",
        "False negatives (full)": "false_negatives.md",
        "Rescues": "rescues.md",
        "All predictions": "predictions.jsonl",
        "Rescues (JSONL)": "rescues.jsonl",
        "False positives (JSONL)": "false_positives.jsonl",
        "False negatives (JSONL)": "false_negatives.jsonl",
    }

    md = build_report_md(
        report=report,
        per_entity=out["per_entity"],
        per_doc=out["per_doc"],
        all_fp=out["all_fp"],
        all_fn=out["all_fn"],
        doc_text_by_name=out["doc_text_by_name"],
        artifact_names=artifact_names,
    )

    fp_md = build_false_positives_md(out["all_fp"], out["doc_text_by_name"], run_id=run_id)
    fn_md = build_false_negatives_md(out["all_fn"], out["doc_text_by_name"], run_id=run_id)
    rescues_md = build_rescues_md(out["rescues"], out["doc_text_by_name"], run_id=run_id)

    write_json(out_dir / "report.json", report)
    (out_dir / "report.md").write_text(md, encoding="utf-8")
    (out_dir / "false_positives.md").write_text(fp_md, encoding="utf-8")
    (out_dir / "false_negatives.md").write_text(fn_md, encoding="utf-8")
    (out_dir / "rescues.md").write_text(rescues_md, encoding="utf-8")

    with (out_dir / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for pred in out["all_pred"]:
            handle.write(json.dumps(predspan_to_json_obj(pred), ensure_ascii=False) + "\n")

    with (out_dir / "rescues.jsonl").open("w", encoding="utf-8") as handle:
        for pred in out["rescues"]:
            handle.write(json.dumps(predspan_to_json_obj(pred), ensure_ascii=False) + "\n")

    with (out_dir / "false_positives.jsonl").open("w", encoding="utf-8") as handle:
        for pred in out["all_fp"]:
            handle.write(json.dumps(predspan_to_json_obj(pred), ensure_ascii=False) + "\n")

    def gold_fn_obj(gold: GoldSpan) -> Dict[str, Any]:
        return {
            "doc": gold.source_file,
            "start": gold.start,
            "end": gold.end,
            "text": gold.text,
            "entity_id": gold.entity_id,
            "winner_kind": None,
        }

    with (out_dir / "false_negatives.jsonl").open("w", encoding="utf-8") as handle:
        for gold in out["all_fn"]:
            handle.write(json.dumps(gold_fn_obj(gold), ensure_ascii=False) + "\n")


def run_eval_and_write(
    *,
    repo_root: Path,
    eval_config: EvalConfig,
    scanner_config: Optional[ScannerConfig] = None,
    out_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> Path:
    out = run_eval(
        repo_root=repo_root,
        eval_config=eval_config,
        scanner_config=scanner_config,
    )
    resolved_run_id = run_id or eval_config.run_id or "eval"
    resolved_out_dir = out_dir or eval_config.out_dir
    if resolved_out_dir is None:
        raise ValueError("out_dir is required (pass out_dir= or eval_config.out_dir)")
    report = dict(out["report"])
    report["run_id"] = resolved_run_id
    write_eval_artifacts(resolved_out_dir, resolved_run_id, out, report)
    return resolved_out_dir / "report.json"


def _warn_if_ner_inactive(
    *,
    skip_ner: bool,
    ner_backend: str,
    timing_rows: List[Dict[str, Any]],
    batched: bool = False,
) -> None:
    if skip_ner:
        return
    if batched:
        # Batched runs share one NER forward pass and record no per-document stage timings,
        # so ner_tokenize_infer_s is legitimately absent here — checking it would falsely
        # report NER as inactive. Re-run with --no-batched for the per-stage breakdown.
        return
    ner_infer_s = sum(
        float((row.get("stages") or {}).get("ner_tokenize_infer_s") or 0.0)
        for row in timing_rows
    )
    if ner_infer_s > 0.0:
        return
    msg = (
        f"NER backend {ner_backend!r} was requested (skip_ner=False) but did not run "
        f"(ner_tokenize_infer_s=0). Eval results are deterministic + contextual only. "
        "For GLiNER on macOS 13.0–13.3: pip install 'onnxruntime>=1.17,<1.18' 'numpy<2' "
        "(see requirements.txt)."
    )
    warnings.warn(msg, UserWarning, stacklevel=2)
    print(f"WARNING: {msg}", file=sys.stderr)


def run_eval(
    *,
    repo_root: Path,
    eval_config: EvalConfig,
    scanner_config: Optional[ScannerConfig] = None,
) -> Dict[str, Any]:
    scanner_config = scanner_config or ScannerConfig()
    gold_dir = eval_config.gold_dir
    min_fused_confidence = eval_config.min_fused_confidence
    warmup = eval_config.warmup
    batched = eval_config.batched

    predictor = SeibaScannerPredictor.from_scanner_config(scanner_config)

    if warmup:
        predictor.warmup(min_fused_confidence=min_fused_confidence)

    per_doc: Dict[str, Any] = {}
    all_gold: List[GoldSpan] = []
    all_pred: List[PredSpan] = []
    doc_text_by_name: Dict[str, str] = {}
    timing_rows: List[Dict[str, Any]] = []
    allowed_union: Optional[set[str]] = None

    gold_docs = [
        load_gold_jsonl(gold_path, repo_root=repo_root)
        for gold_path in discover_gold_files(gold_dir)
    ]

    # One batched pass over every document (NER batches into a single forward pass), or a
    # per-document loop when the caller wants the per-stage timing breakdown.
    batch_wall_s: Optional[float] = None
    preds_by_index: Dict[int, List[PredSpan]] = {}
    if batched:
        t_batch0 = time.perf_counter()
        batched_preds = predictor.predict_many(
            [gdoc.text for gdoc in gold_docs],
            [gdoc.source_file for gdoc in gold_docs],
            min_fused_confidence=min_fused_confidence,
        )
        batch_wall_s = time.perf_counter() - t_batch0
        preds_by_index = dict(enumerate(batched_preds))

    for doc_index, gdoc in enumerate(gold_docs):
        doc = gdoc.source_file
        doc_text_by_name[doc] = gdoc.text

        allowed = set(gdoc.allowed_entity_ids) if gdoc.allowed_entity_ids else None
        if allowed is not None:
            allowed_union = allowed if allowed_union is None else (allowed_union | allowed)

        char_len = len(gdoc.text)
        if batched:
            preds = preds_by_index[doc_index]
        else:
            t_wall0 = time.perf_counter()
            preds, stages = predictor.predict_profiled(
                gdoc.text,
                doc=doc,
                min_fused_confidence=min_fused_confidence,
            )
            wall_s = time.perf_counter() - t_wall0

            timing_rows.append(
                {
                    "doc": doc,
                    "doc_index": doc_index,
                    "char_len": char_len,
                    "wall_classify_s": wall_s,
                    "ms_per_1k_chars": ms_per_1k_chars(wall_s, char_len),
                    "stages": stages,
                    "llm_s": float(stages.get("llm_s", 0.0)) if stages else 0.0,
                }
            )

        gold_spans = list(gdoc.spans)
        if allowed is not None:
            gold_spans = [span for span in gold_spans if span.entity_id in allowed]
            preds = [pred for pred in preds if pred.entity_id in allowed]

        local = score_predictions(gold_spans, preds)
        micro_local = micro_from_entity_metrics(local["per_entity"])
        per_doc[doc] = {
            "precision": micro_local.precision,
            "recall": micro_local.recall,
            "f1": micro_local.f1,
            "support": sum(metric.counts.support for metric in local["per_entity"].values()),
        }

        all_gold.extend(gold_spans)
        all_pred.extend(preds)

    scored = score_predictions(all_gold, all_pred, entity_ids=allowed_union)
    match = scored["match"]
    strict = scored["strict"]
    per_entity = scored["per_entity"]
    per_entity_strict = scored["per_entity_strict"]
    rescue = rescue_diagnostics(match.tp, match.fp)
    llm_attr = (
        llm_attribution_metrics(match.tp, match.fp, match.fn, all_gold)
        if scanner_config.llm_backend is not None
        else None
    )
    winner_breakdown = winner_kind_breakdown(match.tp, match.fp)

    timing_block: Dict[str, Any] = {
        "per_doc": timing_rows,
        "profile_enabled": not batched,
        "warmup_ran": bool(warmup),
        "llm_total_s": sum(row.get("llm_s", 0.0) for row in timing_rows),
        "batched": batched,
    }
    if batch_wall_s is not None:
        # Batched runs share one NER forward pass across documents, so the cost is a
        # property of the batch; per-document stage timings do not exist to report.
        total_chars = sum(len(gdoc.text) for gdoc in gold_docs)
        timing_block["batch_wall_s"] = batch_wall_s
        timing_block["batch_docs"] = len(gold_docs)
        timing_block["batch_ms_per_doc"] = (
            (batch_wall_s * 1000.0 / len(gold_docs)) if gold_docs else 0.0
        )
        timing_block["batch_ms_per_1k_chars"] = ms_per_1k_chars(batch_wall_s, total_chars)

    report = build_report_dict(
        ReportContext(
            run_id="",
            git_sha=git_sha(repo_root),
            config={
                "gold_dir": str(gold_dir),
                "min_fused_confidence": float(min_fused_confidence),
                "skip_ner": bool(scanner_config.skip_ner),
                "fusion_weights": [
                    DEFAULT_FUSION_WEIGHT_DETERMINISTIC,
                    DEFAULT_FUSION_WEIGHT_CONTEXTUAL,
                ],
                "warmup": bool(warmup),
                "ner_backend": scanner_config.ner_backend.value,
                "ner_model": scanner_config.ner_model,
                "llm_backend": (
                    scanner_config.llm_backend.value if scanner_config.llm_backend else None
                ),
                "llm_model": scanner_config.llm_model,
                "llm_coverage": scanner_config.llm_coverage.value,
                "llm_skip_if_above": float(scanner_config.llm_skip_if_above),
            },
            matcher=match,
            strict=strict,
            per_entity=per_entity,
            per_entity_strict=per_entity_strict,
            per_doc=per_doc,
            rescue=rescue,
            timing=timing_block,
            llm_attribution=llm_attr,
            winner_kind_breakdown=winner_breakdown,
        )
    )

    rescues = [pred for pred in all_pred if pred.rescue_applied]
    _warn_if_ner_inactive(
        skip_ner=scanner_config.skip_ner,
        ner_backend=scanner_config.ner_backend.value,
        timing_rows=timing_rows,
        batched=batched,
    )

    return {
        "report": report,
        "per_entity": per_entity,
        "per_doc": per_doc,
        "all_fp": list(match.fp),
        "all_fn": list(match.fn),
        "doc_text_by_name": doc_text_by_name,
        "all_pred": all_pred,
        "rescues": rescues,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run quantified eval against gold spans.")
    ap.add_argument(
        "--gold-dir",
        default=None,
        help="Gold directory (recursive *.gold.jsonl). Default: eval/ground_truth/ACTIVE or unstructured_v2",
    )
    ap.add_argument("--min-fused-confidence", type=float, default=DEFAULT_MIN_FUSED_CONFIDENCE)
    ap.add_argument("--skip-ner", action="store_true", default=False)
    ap.add_argument(
        "--no-batched",
        dest="batched",
        action="store_false",
        default=True,
        help="Classify per document instead of one batched pass. Same spans, but slower; "
        "use it to get the per-document per-stage timing breakdown.",
    )
    ap.add_argument(
        "--warmup",
        action="store_true",
        default=False,
        help="Run a throwaway classify after SDK init to absorb some cold-start cost.",
    )
    ap.add_argument(
        "--baseline-path",
        default="eval/baselines/unstructured_baseline.json",
        help="Baseline JSON path used with --update-baseline",
    )
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        default=False,
        help="Overwrite --baseline-path with this run's report.json",
    )
    ap.add_argument(
        "--ner-backend",
        default="spacy",
        choices=("spacy", "openmed"),
        help="NER backend to use (default: spacy).",
    )
    ap.add_argument("--ner-model", default=None, help="Override the default model for the chosen NER backend.")
    ap.add_argument(
        "--enable-llm",
        action="store_true",
        default=False,
        help="Enable LLM gap-fill with defaults (transformers backend, Qwen/Qwen2.5-3B-Instruct).",
    )
    ap.add_argument(
        "--llm-backend",
        default=None,
        choices=("transformers", "ollama", "llama_cpp", "vllm"),
        help="LLM gap-fill backend (default when --enable-llm: transformers).",
    )
    ap.add_argument(
        "--llm-model",
        default=None,
        help="LLM model name or HF model ID (default when --enable-llm: Qwen/Qwen2.5-3B-Instruct).",
    )
    ap.add_argument("--llm-base-url", default=None, help="Base URL for openai-compatible/ollama/vllm backends.")
    ap.add_argument("--llm-api-key", default=None, help="API key for openai backend (falls back to OPENAI_API_KEY).")
    ap.add_argument(
        "--llm-concurrency",
        type=int,
        default=4,
        help="Parallel chunk workers for API backends (default 4). Set to 1 for local CPU.",
    )
    ap.add_argument(
        "--llm-coverage",
        default="gaps",
        choices=("gaps", "full"),
        help="LLM coverage: gaps (default) skips entity types already at high confidence; full asks for all.",
    )
    ap.add_argument(
        "--llm-skip-if-above",
        type=float,
        default=0.85,
        help="Skip entity type for LLM if already detected above this confidence (default 0.85).",
    )
    ap.add_argument(
        "--output-dir",
        default=None,
        help="Write artifacts here instead of eval/runs/<timestamp>-<backend>.",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    gold_dir = resolve_gold_dir(repo_root, gold_dir_arg=args.gold_dir)

    llm_active = args.enable_llm or (args.llm_backend is not None)
    resolved_llm_backend = (args.llm_backend or "transformers") if llm_active else None
    resolved_llm_model = (args.llm_model or "Qwen/Qwen2.5-3B-Instruct") if llm_active else None

    run_id = now_run_id(args.ner_backend, f"llm_{resolved_llm_backend}" if resolved_llm_backend else "")
    out_dir = Path(args.output_dir) if args.output_dir else repo_root / "eval" / "runs" / run_id
    if not out_dir.is_absolute():
        out_dir = (repo_root / out_dir).resolve()
    ensure_dir(out_dir)
    ensure_dir(repo_root / "eval" / "baselines")

    scanner_config = ScannerConfig(
        skip_ner=args.skip_ner,
        ner_backend=args.ner_backend,
        ner_model=args.ner_model,
        llm_backend=resolved_llm_backend,
        llm_model=resolved_llm_model,
        llm_base_url=args.llm_base_url,
        llm_api_key=args.llm_api_key,
        llm_coverage=args.llm_coverage,
        llm_skip_if_above=args.llm_skip_if_above,
        llm_concurrency=args.llm_concurrency,
    )
    eval_config = EvalConfig(
        gold_dir=gold_dir,
        min_fused_confidence=args.min_fused_confidence,
        warmup=args.warmup,
        out_dir=out_dir,
        run_id=run_id,
        batched=args.batched,
    )
    report_path = run_eval_and_write(
        repo_root=repo_root,
        eval_config=eval_config,
        scanner_config=scanner_config,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    if args.update_baseline:
        baseline_path = (repo_root / args.baseline_path).resolve()
        write_json(baseline_path, report)

    micro = report["headline"]["micro"]
    print(
        f"Eval complete. Micro F1={micro['f1']:.3f} (P/R={micro['precision']:.3f}/{micro['recall']:.3f}). "
        f"Reports: {out_dir / 'report.md'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
