"""Cross-backend scoring: OpenMed predictions mapped to ontology vs unstructured_v2 gold."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from eval.discovery import resolve_gold_dir
from eval.openmed_runner import _write_fp_fn_md, _write_report_md
from eval.scoring import score_openmed_mapped_on_ontology_gold
from eval.util import bootstrap_repo_paths, discover_txt

_repo_root = Path(__file__).resolve().parents[1]
bootstrap_repo_paths(_repo_root)


def load_pred_rows(predictions_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in predictions_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def score_openmed_run(
    *,
    predictions_path: Path,
    gold_dir: Path,
    input_dir: Path,
    map_path: Optional[Path],
    merge_person_names: bool,
    run_id: str,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    files = discover_txt(input_dir)
    pred_rows = load_pred_rows(predictions_path)
    pii_rows = [row for row in pred_rows if row.get("task", "pii") == "pii"]
    if not pii_rows:
        raise ValueError(f"No PII rows in {predictions_path}")

    score = score_openmed_mapped_on_ontology_gold(
        pred_rows=pii_rows,
        gold_dir=gold_dir,
        repo_root=_repo_root,
        files=files,
        map_path=map_path,
        merge_person_names=merge_person_names,
    )

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "task": "pii_mapped",
            "model": "openmed-mapped-to-ontology",
            "total_processing_time_s": 0.0,
        }
        _write_report_md(
            out_dir / "report_ontology_mapped.md",
            run_id,
            meta,
            score,
            [],
            task="pii",
            title="OpenMed → ontology mapped evaluation",
        )
        _write_fp_fn_md(
            out_dir / "false_positives_ontology_mapped.md",
            "Mapped false positives (type_overlap)",
            score["type_overlap"]["false_positives"],
        )
        _write_fp_fn_md(
            out_dir / "false_negatives_ontology_mapped.md",
            "Mapped false negatives (type_overlap)",
            score["type_overlap"]["false_negatives"],
        )
        (out_dir / "report_ontology_mapped.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "scoring": score,
                    "predictions_path": str(predictions_path),
                    "gold_dir": str(gold_dir),
                },
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

    return score


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Score OpenMed PII predictions (label-mapped) vs unstructured_v2 ontology gold."
    )
    ap.add_argument(
        "--openmed-run",
        help="OpenMed run directory (uses predictions.jsonl inside).",
    )
    ap.add_argument(
        "--predictions",
        help="Path to predictions.jsonl (alternative to --openmed-run).",
    )
    ap.add_argument("--input-dir", default="test_data/unstructured")
    ap.add_argument(
        "--gold-dir",
        default="",
        help="Ontology gold dir (default: ACTIVE / unstructured_v2).",
    )
    ap.add_argument(
        "--map-path",
        default="eval/label_maps/openmed_to_ontology.yaml",
        help="OpenMed → ontology label map YAML.",
    )
    ap.add_argument(
        "--no-merge-person-names",
        action="store_true",
        help="Disable merging adjacent first/last name spans into person_names.",
    )
    ap.add_argument(
        "--out-dir",
        default="",
        help="Write mapped report artifacts here (defaults to openmed run dir).",
    )
    args = ap.parse_args()

    if not args.openmed_run and not args.predictions:
        print("Provide --openmed-run or --predictions", file=sys.stderr)
        return 1

    if args.predictions:
        predictions_path = (_repo_root / args.predictions).resolve()
        run_id = predictions_path.parent.name
        default_out = predictions_path.parent
    else:
        run_dir = (_repo_root / args.openmed_run).resolve()
        predictions_path = run_dir / "predictions.jsonl"
        run_id = run_dir.name
        default_out = run_dir

    if not predictions_path.is_file():
        print(f"Missing predictions: {predictions_path}", file=sys.stderr)
        return 1

    gold_dir = (
        resolve_gold_dir(_repo_root, gold_dir_arg=args.gold_dir or None)
        if args.gold_dir
        else resolve_gold_dir(_repo_root)
    )
    input_dir = (_repo_root / args.input_dir).resolve()
    map_path = (_repo_root / args.map_path).resolve()
    out_dir = (_repo_root / args.out_dir).resolve() if args.out_dir else default_out

    score = score_openmed_run(
        predictions_path=predictions_path,
        gold_dir=gold_dir,
        input_dir=input_dir,
        map_path=map_path,
        merge_person_names=not args.no_merge_person_names,
        run_id=run_id,
        out_dir=out_dir,
    )
    micro = score["type_overlap"]["micro"]
    print(
        f"Mapped ontology micro F1={micro['f1']:.3f} "
        f"P={micro['precision']:.3f} R={micro['recall']:.3f} "
        f"(gold={gold_dir})"
    )
    if out_dir:
        print(f"Wrote {out_dir / 'report_ontology_mapped.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
