"""OpenMed prediction runner with PII and clinical scoring vs OpenMed-label gold."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from eval.openmed_util import entities_from_result, openmed_eager_config
from eval.scoring import (
    score_openmed_clinical_predictions,
    score_openmed_mapped_on_ontology_gold,
    score_openmed_pii_predictions,
)
from eval.util import bootstrap_repo_paths, discover_txt, ensure_dir, model_slug, now_run_id

_repo_root = Path(__file__).resolve().parents[1]
bootstrap_repo_paths(_repo_root)

DEFAULT_PII_MODEL = "OpenMed/OpenMed-PII-SuperClinical-Small-44M-v1"
DEFAULT_CLINICAL_MODEL = "OpenMed/OpenMed-NER-DiseaseDetect-BigMed-560M"


def _model_labels(model_name: str, config) -> Dict[str, Any]:
    try:
        from openmed import load_model

        bundle = load_model(model_name, config=config)
        model = bundle["model"] if isinstance(bundle, dict) else bundle
        id2label = dict(getattr(model.config, "id2label", {}) or {})
        ent_types = sorted(
            {value.split("-", 1)[-1] for value in id2label.values() if value not in ("O", "o")}
        )
        return {
            "id2label": {str(key): value for key, value in id2label.items()},
            "entity_types": ent_types,
            "num_entity_types": len(ent_types),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _run_task(
    task: str,
    model_name: str,
    files: List[Path],
    config,
    batch_size: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    from openmed import BatchProcessor

    operation = "extract_pii" if task == "pii" else "analyze_text"
    processor = BatchProcessor(
        model_name=model_name,
        operation=operation,
        batch_size=batch_size,
        config=config,
        continue_on_error=True,
    )
    batch = processor.process_files([str(path) for path in files])
    by_name = {path.name: path for path in files}

    pred_rows: List[Dict[str, Any]] = []
    per_file: List[Dict[str, Any]] = []
    for item in batch.items:
        src = Path(item.source).name if item.source else str(item.id)
        char_len = len(by_name[src].read_text(encoding="utf-8")) if src in by_name else None
        ents = entities_from_result(item.result)
        per_file.append(
            {
                "task": task,
                "model": model_name,
                "doc": src,
                "char_len": char_len,
                "num_entities": len(ents),
                "processing_time_s": item.processing_time,
                "ms_per_1k_chars": (
                    round(item.processing_time * 1000 / (char_len / 1000), 2)
                    if item.processing_time and char_len
                    else None
                ),
                "error": item.error,
            }
        )
        for entity in ents:
            pred_rows.append({"task": task, "model": model_name, "doc": src, **entity})

    task_meta = {
        "task": task,
        "model": model_name,
        "operation": operation,
        "total_processing_time_s": batch.total_processing_time,
        "started_at": str(getattr(batch, "started_at", None)),
        "completed_at": str(getattr(batch, "completed_at", None)),
        "labels": _model_labels(model_name, config),
    }
    return pred_rows, per_file, task_meta


def _run_task_hf(
    model_name: str,
    files: List[Path],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    """PII spans from the raw HF token-classification model (no OpenMed SDK).

    Isolates the fine-tuned transformer from the SDK's BIOES/Viterbi decoding and span
    refinement, so a run scored on the same gold shows what the SDK layer actually adds.
    """
    from transformers import pipeline

    pipe = pipeline(
        "token-classification",
        model=model_name,
        aggregation_strategy="simple",
        model_kwargs={"attn_implementation": "eager"},
    )
    id2label = dict(getattr(pipe.model.config, "id2label", {}) or {})
    ent_types = sorted({v.split("-", 1)[-1] for v in id2label.values() if v not in ("O", "o")})

    pred_rows: List[Dict[str, Any]] = []
    per_file: List[Dict[str, Any]] = []
    total_time = 0.0
    for path in files:
        text = path.read_text(encoding="utf-8")
        char_len = len(text)
        t0 = time.perf_counter()
        ents = pipe(text)
        elapsed = time.perf_counter() - t0
        total_time += elapsed
        per_file.append(
            {
                "task": "pii",
                "model": model_name,
                "doc": path.name,
                "char_len": char_len,
                "num_entities": len(ents),
                "processing_time_s": elapsed,
                "ms_per_1k_chars": round(elapsed * 1000 / (char_len / 1000), 2) if char_len else None,
                "error": None,
            }
        )
        for ent in ents:
            start, end = int(ent["start"]), int(ent["end"])
            pred_rows.append(
                {
                    "task": "pii",
                    "model": model_name,
                    "doc": path.name,
                    "label": ent["entity_group"],
                    "text": text[start:end],
                    "start": start,
                    "end": end,
                    "confidence": float(ent["score"]),
                }
            )

    task_meta = {
        "task": "pii",
        "model": model_name,
        "operation": "token-classification (transformers)",
        "total_processing_time_s": total_time,
        "started_at": None,
        "completed_at": None,
        "labels": {
            "id2label": {str(key): value for key, value in id2label.items()},
            "entity_types": ent_types,
            "num_entity_types": len(ent_types),
        },
    }
    return pred_rows, per_file, task_meta


def _label_histogram(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    hist: Dict[str, Dict[str, int]] = {}
    for row in rows:
        task = row.get("task", "?")
        label = row.get("label", "?")
        hist.setdefault(task, {})
        hist[task][label] = hist[task].get(label, 0) + 1
    return {task: dict(sorted(counts.items(), key=lambda kv: -kv[1])) for task, counts in hist.items()}


def _write_summary_md(
    path: Path,
    run_id: str,
    tasks_meta: List[Dict[str, Any]],
    per_file: List[Dict[str, Any]],
    hist: Dict[str, Dict[str, int]],
) -> None:
    lines = [f"# OpenMed prediction run — `{run_id}`\n", "> Raw predictions + latency.\n"]
    for meta in tasks_meta:
        labels = meta.get("labels", {})
        lines.append(f"## Task `{meta['task']}` — `{meta['model']}`\n")
        lines.append(f"- operation: `{meta['operation']}`")
        total = meta.get("total_processing_time_s")
        if isinstance(total, (int, float)):
            lines.append(f"- total processing time: **{total:.3f}s**")
        lines.append(f"- model entity-types supported: **{labels.get('num_entity_types', '?')}**\n")

    lines.append("## Per-file latency & counts\n")
    lines.append("| task | doc | chars | #entities | time (s) | ms/1k |")
    lines.append("|------|-----|-------|-----------|----------|-------|")
    for row in per_file:
        timing = row["processing_time_s"]
        timing_s = f"{timing:.3f}" if isinstance(timing, (int, float)) else str(timing)
        lines.append(
            f"| {row['task']} | {row['doc']} | {row['char_len']} | {row['num_entities']} "
            f"| {timing_s} | {row['ms_per_1k_chars']} |"
        )
    lines.append("")

    lines.append("## Predicted label frequency\n")
    for task, counts in hist.items():
        lines.append(f"### {task}\n")
        lines.append("| label | count |")
        lines.append("|-------|-------|")
        for label, count in counts.items():
            lines.append(f"| {label} | {count} |")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_report_md(
    path: Path,
    run_id: str,
    task_meta: Dict[str, Any],
    score: Dict[str, Any],
    per_file: List[Dict[str, Any]],
    *,
    task: str = "pii",
    title: str = "OpenMed PII evaluation",
) -> None:
    overlap, strict = score["type_overlap"], score["strict"]
    lines = [
        f"# {title} — `{run_id}`\n",
        f"- model: `{task_meta['model']}`",
        f"- scored documents: **{overlap['scored_docs']}**",
        f"- total NER latency ({task} task): **{task_meta['total_processing_time_s']:.3f}s**\n",
        "## Headline metrics\n",
        "| matching | precision | recall | F1 | TP | FP | FN |",
        "|----------|-----------|--------|----|----|----|----|",
    ]
    for name, metrics in (("type_overlap", overlap), ("strict", strict)):
        micro = metrics["micro"]
        lines.append(
            f"| micro ({name}) | {micro['precision']:.3f} | {micro['recall']:.3f} | "
            f"{micro['f1']:.3f} | {micro['tp']} | {micro['fp']} | {micro['fn']} |"
        )
    lines.append(
        f"| macro (type_overlap) | {overlap['macro']['precision']:.3f} | "
        f"{overlap['macro']['recall']:.3f} | {overlap['macro']['f1']:.3f} | | | |"
    )
    lines.append("")

    lines.append("## Per-entity metrics (type_overlap)\n")
    lines.append("| entity | precision | recall | F1 | TP | FP | FN | support |")
    lines.append("|--------|-----------|--------|----|----|----|----|---------|")
    for eid, value in sorted(overlap["per_entity"].items(), key=lambda kv: (-kv[1]["support"], kv[0])):
        lines.append(
            f"| {eid.split('::')[-1]} | {value['precision']:.3f} | {value['recall']:.3f} | "
            f"{value['f1']:.3f} | {value['tp']} | {value['fp']} | {value['fn']} | {value['support']} |"
        )
    lines.append("")

    lines.append("## Per-file latency\n")
    lines.append("| doc | chars | #pred | time (s) | ms/1k |")
    lines.append("|-----|-------|-------|----------|-------|")
    for row in per_file:
        if row["task"] != task:
            continue
        timing = row["processing_time_s"]
        timing_s = f"{timing:.3f}" if isinstance(timing, (int, float)) else str(timing)
        lines.append(
            f"| {row['doc']} | {row['char_len']} | {row['num_entities']} | {timing_s} | {row['ms_per_1k_chars']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_fp_fn_md(path: Path, title: str, items: List[Dict[str, Any]]) -> None:
    lines = [f"# {title} ({len(items)})\n"]
    by_entity: Dict[str, list] = {}
    for item in items:
        by_entity.setdefault(item["entity_id"].split("::")[-1], []).append(item)
    for entity in sorted(by_entity, key=lambda key: -len(by_entity[key])):
        lines.append(f"## {entity} ({len(by_entity[entity])})\n")
        for item in by_entity[entity]:
            conf = f" conf={item['confidence']:.2f}" if "confidence" in item else ""
            lines.append(f"- `{item['doc']}` [{item['start']}:{item['end']}]{conf} — {item['text']!r}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run(
    input_dir: Path,
    out_root: Path,
    pii_model: str,
    clinical_model: Optional[str],
    batch_size: int,
    tasks: List[str],
    gold_dir: Optional[Path] = None,
    ontology_gold_dir: Optional[Path] = None,
    only_docs: Optional[set] = None,
    engine: str = "sdk",
) -> Path:
    config = openmed_eager_config() if engine == "sdk" else None
    files = discover_txt(input_dir, only=only_docs)
    run_id = now_run_id("openmed", engine, model_slug(pii_model))
    out_dir = out_root / run_id
    ensure_dir(out_dir)

    all_preds: List[Dict[str, Any]] = []
    all_per_file: List[Dict[str, Any]] = []
    tasks_meta: List[Dict[str, Any]] = []
    task_models = {"pii": pii_model, "clinical": clinical_model}
    if engine == "transformers":
        tasks = ["pii"]  # raw transformer path is PII-only (clinical is an SDK operation)

    for task in tasks:
        model_name = task_models.get(task)
        if not model_name:
            continue
        print(f"[openmed:{engine}] running task={task} model={model_name} over {len(files)} files ...")
        if engine == "transformers":
            preds, per_file, meta = _run_task_hf(model_name, files)
        else:
            preds, per_file, meta = _run_task(task, model_name, files, config, batch_size)
        all_preds.extend(preds)
        all_per_file.extend(per_file)
        tasks_meta.append(meta)
        print(f"[openmed]   -> {len(preds)} spans, {meta['total_processing_time_s']}s")

    preds_path = out_dir / "predictions.jsonl"
    with preds_path.open("w", encoding="utf-8") as handle:
        for row in all_preds:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    hist = _label_histogram(all_preds)
    run_obj = {
        "run_id": run_id,
        "input_dir": str(input_dir),
        "num_files": len(files),
        "files": [path.name for path in files],
        "batch_size": batch_size,
        "tasks": tasks_meta,
        "per_file": all_per_file,
        "label_histogram": hist,
        "total_spans": len(all_preds),
    }
    (out_dir / "run.json").write_text(
        json.dumps(run_obj, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    _write_summary_md(out_dir / "summary.md", run_id, tasks_meta, all_per_file, hist)

    print("\n[openmed] wrote:")
    print(f"  {preds_path}")
    print(f"  {out_dir / 'run.json'}")
    print(f"  {out_dir / 'summary.md'}")

    pii_meta = next((meta for meta in tasks_meta if meta["task"] == "pii"), None)
    clinical_meta = next((meta for meta in tasks_meta if meta["task"] == "clinical"), None)
    has_pii_preds = any(row["task"] == "pii" for row in all_preds)
    has_clinical_preds = any(row["task"] == "clinical" for row in all_preds)
    scoring: Dict[str, Any] = {}

    if gold_dir and gold_dir.is_dir() and pii_meta and has_pii_preds:
        print(f"[openmed] scoring PII vs gold: {gold_dir}")
        pii_score = score_openmed_pii_predictions(pred_rows=all_preds, gold_dir=gold_dir, files=files)
        scoring["pii"] = {
            key: {inner: value for inner, value in metrics.items() if inner not in ("false_positives", "false_negatives")}
            for key, metrics in pii_score.items()
        }
        (out_dir / "report.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "model": pii_meta["model"],
                    "total_processing_time_s": pii_meta["total_processing_time_s"],
                    "scoring": {"pii": pii_score},
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        _write_report_md(
            out_dir / "report.md",
            run_id,
            pii_meta,
            pii_score,
            all_per_file,
            task="pii",
            title="OpenMed PII evaluation",
        )
        _write_fp_fn_md(
            out_dir / "false_positives.md",
            "False positives (type_overlap)",
            pii_score["type_overlap"]["false_positives"],
        )
        _write_fp_fn_md(
            out_dir / "false_negatives.md",
            "False negatives (type_overlap)",
            pii_score["type_overlap"]["false_negatives"],
        )
        micro = pii_score["type_overlap"]["micro"]
        print(
            f"  {out_dir / 'report.md'}  (PII overlap micro F1={micro['f1']:.3f} "
            f"P={micro['precision']:.3f} R={micro['recall']:.3f})"
        )
        print(f"  {out_dir / 'report.json'}")
    elif gold_dir:
        print("[openmed] skipped PII scoring (no gold dir / PII preds)")

    if ontology_gold_dir and ontology_gold_dir.is_dir() and has_pii_preds:
        print(f"[openmed] scoring mapped PII vs ontology gold: {ontology_gold_dir}")
        mapped_score = score_openmed_mapped_on_ontology_gold(
            pred_rows=all_preds,
            gold_dir=ontology_gold_dir,
            repo_root=_repo_root,
            files=files,
        )
        scoring["pii_ontology_mapped"] = {
            key: {inner: value for inner, value in metrics.items() if inner not in ("false_positives", "false_negatives")}
            for key, metrics in mapped_score.items()
            if key != "mapping"
        }
        _write_report_md(
            out_dir / "report_ontology_mapped.md",
            run_id,
            {
                "task": "pii_mapped",
                "model": pii_meta["model"] if pii_meta else "openmed",
                "total_processing_time_s": pii_meta["total_processing_time_s"] if pii_meta else 0.0,
            },
            mapped_score,
            all_per_file,
            task="pii",
            title="OpenMed → ontology mapped evaluation",
        )
        _write_fp_fn_md(
            out_dir / "false_positives_ontology_mapped.md",
            "Mapped false positives (type_overlap)",
            mapped_score["type_overlap"]["false_positives"],
        )
        _write_fp_fn_md(
            out_dir / "false_negatives_ontology_mapped.md",
            "Mapped false negatives (type_overlap)",
            mapped_score["type_overlap"]["false_negatives"],
        )
        mapped_report_path = out_dir / "report_ontology_mapped.json"
        mapped_report_obj: Dict[str, Any] = {
            "run_id": run_id,
            "scoring": mapped_score,
            "ontology_gold_dir": str(ontology_gold_dir),
        }
        mapped_report_path.write_text(
            json.dumps(mapped_report_obj, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        micro = mapped_score["type_overlap"]["micro"]
        print(
            f"  {out_dir / 'report_ontology_mapped.md'}  (mapped ontology micro F1={micro['f1']:.3f} "
            f"P={micro['precision']:.3f} R={micro['recall']:.3f})"
        )
    elif ontology_gold_dir:
        print("[openmed] skipped ontology-mapped scoring (no PII preds)")

    if gold_dir and gold_dir.is_dir() and clinical_meta and has_clinical_preds:
        print(f"[openmed] scoring clinical vs gold: {gold_dir}")
        clinical_score = score_openmed_clinical_predictions(
            pred_rows=all_preds, gold_dir=gold_dir, files=files
        )
        scoring["clinical"] = {
            key: {inner: value for inner, value in metrics.items() if inner not in ("false_positives", "false_negatives")}
            for key, metrics in clinical_score.items()
        }
        _write_report_md(
            out_dir / "report_clinical.md",
            run_id,
            clinical_meta,
            clinical_score,
            all_per_file,
            task="clinical",
            title="OpenMed clinical evaluation",
        )
        _write_fp_fn_md(
            out_dir / "false_positives_clinical.md",
            "Clinical false positives (type_overlap)",
            clinical_score["type_overlap"]["false_positives"],
        )
        _write_fp_fn_md(
            out_dir / "false_negatives_clinical.md",
            "Clinical false negatives (type_overlap)",
            clinical_score["type_overlap"]["false_negatives"],
        )
        report_path = out_dir / "report.json"
        report_obj: Dict[str, Any] = {}
        if report_path.is_file():
            report_obj = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            report_obj = {"run_id": run_id, "scoring": {}}
        report_obj.setdefault("scoring", {})
        report_obj["scoring"]["clinical"] = clinical_score
        if clinical_meta:
            report_obj["clinical_model"] = clinical_meta["model"]
            report_obj["clinical_total_processing_time_s"] = clinical_meta["total_processing_time_s"]
        report_path.write_text(
            json.dumps(report_obj, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        micro = clinical_score["type_overlap"]["micro"]
        print(
            f"  {out_dir / 'report_clinical.md'}  (clinical overlap micro F1={micro['f1']:.3f} "
            f"P={micro['precision']:.3f} R={micro['recall']:.3f})"
        )
    elif gold_dir and "clinical" in tasks:
        print("[openmed] skipped clinical scoring (no clinical preds)")

    if scoring:
        run_obj["scoring"] = scoring
        (out_dir / "run.json").write_text(
            json.dumps(run_obj, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    elif not (gold_dir and gold_dir.is_dir()):
        print("[openmed] no gold dir -> skipped scoring")
    return out_dir


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenMed runner: predictions + optional PII scoring.")
    ap.add_argument("--input-dir", default="test_data/unstructured")
    ap.add_argument("--out-dir", default="eval/openmed_runs")
    ap.add_argument("--pii-model", default=DEFAULT_PII_MODEL)
    ap.add_argument("--clinical-model", default=DEFAULT_CLINICAL_MODEL)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--tasks", default="pii,clinical", help="Comma list: pii, clinical")
    ap.add_argument(
        "--gold-dir",
        default="eval/ground_truth/openmed",
        help="Gold dir for native OpenMed PII scoring. Empty string disables.",
    )
    ap.add_argument(
        "--ontology-gold-dir",
        default="eval/ground_truth/unstructured_v2",
        help="Ontology gold for label-mapped cross scoring. Empty string disables.",
    )
    ap.add_argument("--docs", default="", help="Comma-separated basenames to restrict to.")
    ap.add_argument(
        "--engine",
        default="sdk",
        choices=("sdk", "transformers"),
        help="sdk: OpenMed BatchProcessor. transformers: raw HF token-classification, no OpenMed SDK.",
    )
    args = ap.parse_args()

    if args.engine == "sdk":
        try:
            import openmed  # noqa: F401
        except ImportError:
            print(
                "[x] openmed not importable in this interpreter.\n"
                "    Use: .venv-openmed/bin/python -m eval.openmed_runner",
                file=sys.stderr,
            )
            return 1
    else:
        try:
            import transformers  # noqa: F401
        except ImportError:
            print(
                "[x] transformers not importable for --engine transformers.\n"
                "    Use: .venv-openmed/bin/python -m eval.openmed_runner --engine transformers",
                file=sys.stderr,
            )
            return 1

    input_dir = (_repo_root / args.input_dir).resolve()
    out_root = (_repo_root / args.out_dir).resolve()
    tasks = [task.strip() for task in args.tasks.split(",") if task.strip()]
    gold_dir = (_repo_root / args.gold_dir).resolve() if args.gold_dir else None
    ontology_gold_dir = (
        (_repo_root / args.ontology_gold_dir).resolve() if args.ontology_gold_dir else None
    )
    only_docs = {doc.strip() for doc in args.docs.split(",") if doc.strip()} or None

    run(
        input_dir=input_dir,
        out_root=out_root,
        pii_model=args.pii_model,
        clinical_model=args.clinical_model,
        batch_size=args.batch_size,
        tasks=tasks,
        gold_dir=gold_dir,
        ontology_gold_dir=ontology_gold_dir,
        only_docs=only_docs,
        engine=args.engine,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
