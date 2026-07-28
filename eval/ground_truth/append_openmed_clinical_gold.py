"""Append OpenMed clinical spans to existing PII gold JSONL files."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from eval.ground_truth.openmed_clinical_annotations import OPENMED_CLINICAL_BY_DOC
from eval.openmed_clinical import DEFAULT_CLINICAL_LABEL_SET, OPENMED_CLINICAL_ENTITY_IDS

GOLD_DIR = _repo_root / "eval" / "ground_truth" / "openmed"
TEXT_DIR = _repo_root / "test_data" / "unstructured"


def _find_non_overlapping(text: str, phrase: str) -> List[Tuple[int, int, str]]:
    spans: List[Tuple[int, int, str]] = []
    start = 0
    while True:
        idx = text.find(phrase, start)
        if idx < 0:
            break
        spans.append((idx, idx + len(phrase), phrase))
        start = idx + len(phrase)
    return spans


def _existing_keys(lines: List[str]) -> Set[Tuple[int, int, str]]:
    keys: Set[Tuple[int, int, str]] = set()
    for line in lines[1:]:
        if not line.strip():
            continue
        obj = json.loads(line)
        keys.add((int(obj["start"]), int(obj["end"]), obj["entity_id"]))
    return keys


def append_clinical_gold(*, dry_run: bool = False) -> None:
    total_added = 0
    for doc_stem, phrases in sorted(OPENMED_CLINICAL_BY_DOC.items()):
        gold_path = GOLD_DIR / f"{doc_stem}.gold.jsonl"
        text_path = TEXT_DIR / f"{doc_stem}.txt"
        if not gold_path.is_file():
            raise FileNotFoundError(f"Missing gold file: {gold_path}")
        if not text_path.is_file():
            raise FileNotFoundError(f"Missing source text: {text_path}")

        text = text_path.read_text(encoding="utf-8")
        lines = gold_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise ValueError(f"Empty gold file: {gold_path}")

        meta_obj = json.loads(lines[0])
        meta: Dict[str, Any] = dict(meta_obj["_meta"])
        meta["clinical_label_set"] = DEFAULT_CLINICAL_LABEL_SET
        meta["clinical_allowed_entity_ids"] = sorted(OPENMED_CLINICAL_ENTITY_IDS)
        meta["clinical_annotation_notes"] = (
            "Patient-specific disease/condition/pathology spans for OpenMed DiseaseDetect TinyMed 65M. "
            "Family-history-only mentions and negated conditions are excluded."
        )

        existing = _existing_keys(lines)
        new_rows: List[Dict[str, Any]] = []
        for phrase, label_suffix in phrases:
            entity_id = f"openmed::{label_suffix}"
            if entity_id not in OPENMED_CLINICAL_ENTITY_IDS:
                raise ValueError(f"Unknown clinical label suffix: {label_suffix}")
            for start, end, span_text in _find_non_overlapping(text, phrase):
                key = (start, end, entity_id)
                if key in existing:
                    continue
                actual = text[start:end]
                if actual != span_text:
                    raise ValueError(
                        f"Offset mismatch in {doc_stem} for {phrase!r}: got {actual!r}"
                    )
                new_rows.append(
                    {"start": start, "end": end, "text": span_text, "entity_id": entity_id}
                )
                existing.add(key)

        new_rows.sort(key=lambda row: (row["start"], row["end"], row["entity_id"]))
        if not new_rows:
            print(f"[skip] {doc_stem}: no new clinical spans")
            continue

        total_added += len(new_rows)
        print(f"[{'dry' if dry_run else 'add'}] {doc_stem}: +{len(new_rows)} clinical spans")
        if dry_run:
            continue

        out_lines = [json.dumps({"_meta": meta}, ensure_ascii=False)]
        out_lines.extend(lines[1:])
        for row in new_rows:
            out_lines.append(json.dumps(row, ensure_ascii=False))
        gold_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    print(f"Done. Added {total_added} clinical spans across {len(OPENMED_CLINICAL_BY_DOC)} docs.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    append_clinical_gold(dry_run=dry)
