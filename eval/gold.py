from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

_repo_root = Path(__file__).resolve().parents[1]
_src = _repo_root / "src"
_parent = _repo_root.parent
for _path in (_parent, _repo_root, _src):
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from seiba_risk_scanner import load_entity_configs
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    resolve_entity_alias,
)

from eval.types import GoldSpan


@dataclass(frozen=True)
class GoldDoc:
    source_file: str
    gold_path: Path
    text: str
    spans: List[GoldSpan]
    meta: Dict[str, Any]
    # If provided, evaluation will ignore predictions outside this set.
    allowed_entity_ids: Optional[List[str]] = None


def _must_int(x: Any, *, field: str) -> int:
    try:
        return int(x)
    except Exception as e:
        raise ValueError(f"Invalid int for {field}: {x!r}") from e


def load_gold_jsonl(
    gold_path: Path,
    *,
    repo_root: Path,
    ontology_paths: Optional[List[str]] = None,
) -> GoldDoc:
    """Load a gold JSONL file and validate offsets + entity_id existence.

    Expected JSONL:
      - First line: {"_meta": {"file": "<name>.txt", ... , "allowed_entity_ids": [...]?}}
      - Subsequent: {"start": int, "end": int, "text": "...", "entity_id": "..."}
    """
    raw_lines = gold_path.read_text(encoding="utf-8").splitlines()
    if not raw_lines:
        raise ValueError(f"Gold file is empty: {gold_path}")

    first = json.loads(raw_lines[0])
    if "_meta" not in first or not isinstance(first["_meta"], dict):
        raise ValueError(f"First line must be metadata object with _meta: {gold_path}")
    meta: Dict[str, Any] = dict(first["_meta"])
    src = meta.get("file")
    if not isinstance(src, str) or not src:
        raise ValueError(f"Gold meta must include 'file' string: {gold_path}")

    src_path = repo_root / "test_data" / "unstructured" / src
    if not src_path.exists():
        raise FileNotFoundError(f"Gold meta file not found: {src_path}")
    text = src_path.read_text(encoding="utf-8")

    configs = load_entity_configs(ontology_paths)
    valid_ids = set(configs.keys())

    allowed = meta.get("allowed_entity_ids")
    allowed_entity_ids: Optional[List[str]] = None
    if allowed is not None:
        if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
            raise ValueError(f"_meta.allowed_entity_ids must be a list[str] if present: {gold_path}")
        # Resolved through is_a for the same reason the spans are: a doc that permits
        # physician_names permits the person_names the scanner actually reports.
        allowed_entity_ids = sorted({resolve_entity_alias(x, configs) for x in allowed})

    spans: List[GoldSpan] = []
    for i, line in enumerate(raw_lines[1:], start=2):
        if not line.strip():
            continue
        obj = json.loads(line)
        start = _must_int(obj.get("start"), field=f"start (line {i})")
        end = _must_int(obj.get("end"), field=f"end (line {i})")
        entity_id = obj.get("entity_id")
        span_text = obj.get("text")
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError(f"Missing entity_id on line {i}: {gold_path}")
        if not isinstance(span_text, str):
            raise ValueError(f"Missing text on line {i}: {gold_path}")
        if entity_id not in valid_ids:
            raise ValueError(f"Unknown entity_id {entity_id!r} on line {i}: {gold_path}")
        # Score against the same taxonomy the scanner reports in: an annotation of a
        # subtype (physician_names) and a detection of its parent (person_names) are the
        # same claim, so both sides are resolved through is_a before they are compared.
        entity_id = resolve_entity_alias(entity_id, configs)
        if start < 0 or end < 0 or end < start or end > len(text):
            raise ValueError(f"Invalid span [{start},{end}) on line {i}: {gold_path}")
        actual = text[start:end]
        if actual != span_text:
            raise ValueError(
                f"Span text mismatch on line {i}: {gold_path}\n"
                f"  expected: {span_text!r}\n"
                f"  actual:   {actual!r}\n"
                f"  range:    [{start},{end})"
            )
        spans.append(
            GoldSpan(
                start=start,
                end=end,
                text=span_text,
                entity_id=entity_id,
                source_file=src,
            )
        )

    spans.sort(key=lambda s: (s.start, s.end, s.entity_id))
    return GoldDoc(
        source_file=src,
        gold_path=gold_path,
        text=text,
        spans=spans,
        meta=meta,
        allowed_entity_ids=allowed_entity_ids,
    )


def load_gold_spans_loose(
    gold_path: Path,
    source_file: str,
    *,
    entity_ids: Optional[Iterable[str]] = None,
    exclude_entity_ids: Optional[Iterable[str]] = None,
) -> Optional[List[GoldSpan]]:
    """Load spans from gold JSONL without ontology validation (OpenMed namespace)."""
    if not gold_path.is_file():
        return None
    allow: Optional[Set[str]] = set(entity_ids) if entity_ids is not None else None
    deny: Set[str] = set(exclude_entity_ids) if exclude_entity_ids is not None else set()
    spans: List[GoldSpan] = []
    for index, line in enumerate(gold_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        obj = json.loads(line)
        if index == 0 and "_meta" in obj:
            continue
        entity_id = obj["entity_id"]
        if allow is not None and entity_id not in allow:
            continue
        if entity_id in deny:
            continue
        spans.append(
            GoldSpan(
                start=int(obj["start"]),
                end=int(obj["end"]),
                text=obj["text"],
                entity_id=entity_id,
                source_file=source_file,
            )
        )
    return spans

