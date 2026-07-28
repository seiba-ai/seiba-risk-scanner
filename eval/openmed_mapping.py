"""Remap OpenMed PII labels to Seiba ontology entity_ids for cross-backend eval."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from eval.types import PredSpan

DEFAULT_MAP_PATH = Path(__file__).resolve().parent / "label_maps" / "openmed_to_ontology.yaml"
PERSON_NAMES_EID = "pii_entity_ontology::person_names"
OPENMED_PREFIX = "openmed::"


@lru_cache(maxsize=1)
def load_openmed_to_ontology_map(path: Optional[str] = None) -> Dict[str, str]:
    map_path = Path(path) if path else DEFAULT_MAP_PATH
    raw = yaml.safe_load(map_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected mapping dict in {map_path}")
    out: Dict[str, str] = {}
    for key, value in raw.items():
        if key.startswith("_") or value is None:
            continue
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError(f"Invalid mapping entry {key!r} -> {value!r} in {map_path}")
        out[key.strip()] = value.strip()
    return out


def openmed_label_suffix(entity_id: str) -> str:
    if entity_id.startswith(OPENMED_PREFIX):
        return entity_id[len(OPENMED_PREFIX) :]
    return entity_id


def map_openmed_entity_id(entity_id: str, mapping: Dict[str, str]) -> Optional[str]:
    suffix = openmed_label_suffix(entity_id)
    return mapping.get(suffix)


def remap_pred_span(span: PredSpan, target_entity_id: str) -> PredSpan:
    provenance = dict(span.provenance or {})
    provenance["openmed_entity_id"] = span.entity_id
    provenance["mapped_entity_id"] = target_entity_id
    return PredSpan(
        start=span.start,
        end=span.end,
        text=span.text,
        entity_id=target_entity_id,
        confidence=span.confidence,
        winner_kind=span.winner_kind,
        confidence_llm=span.confidence_llm,
        rescue_applied=span.rescue_applied,
        original_entity_id=span.original_entity_id or span.entity_id,
        provenance=provenance,
    )


def remap_pred_spans(
    spans: Sequence[PredSpan],
    *,
    mapping: Optional[Dict[str, str]] = None,
    map_path: Optional[str] = None,
) -> List[PredSpan]:
    label_map = mapping or load_openmed_to_ontology_map(map_path)
    remapped: List[PredSpan] = []
    for span in spans:
        target = map_openmed_entity_id(span.entity_id, label_map)
        if target is None:
            continue
        remapped.append(remap_pred_span(span, target))
    return remapped


def merge_adjacent_person_names(
    spans: Sequence[PredSpan],
    *,
    text: str,
    entity_id: str = PERSON_NAMES_EID,
    max_gap: int = 1,
) -> List[PredSpan]:
    """Merge consecutive person-name spans separated only by whitespace."""
    person = sorted([s for s in spans if s.entity_id == entity_id], key=lambda s: (s.start, s.end))
    other = [s for s in spans if s.entity_id != entity_id]
    if len(person) <= 1:
        return list(spans)

    merged_person: List[PredSpan] = []
    cur = person[0]
    for nxt in person[1:]:
        gap = text[cur.end : nxt.start]
        if nxt.start >= cur.end and len(gap) <= max_gap and (not gap or gap.isspace()):
            start = cur.start
            end = nxt.end
            conf = max(cur.confidence, nxt.confidence)
            cur = PredSpan(
                start=start,
                end=end,
                text=text[start:end],
                entity_id=entity_id,
                confidence=conf,
                winner_kind=cur.winner_kind or nxt.winner_kind,
                confidence_llm=cur.confidence_llm or nxt.confidence_llm,
                rescue_applied=cur.rescue_applied or nxt.rescue_applied,
                original_entity_id=cur.original_entity_id,
                provenance={
                    **(cur.provenance or {}),
                    "merged_person_names": True,
                },
            )
        else:
            merged_person.append(cur)
            cur = nxt
    merged_person.append(cur)
    out = other + merged_person
    out.sort(key=lambda s: (s.start, s.end, s.entity_id))
    return out


def remap_openmed_preds_by_doc(
    preds_by_doc: Dict[str, List[PredSpan]],
    *,
    doc_text_by_name: Dict[str, str],
    mapping: Optional[Dict[str, str]] = None,
    map_path: Optional[str] = None,
    merge_person_names: bool = True,
) -> Dict[str, List[PredSpan]]:
    label_map = mapping or load_openmed_to_ontology_map(map_path)
    out: Dict[str, List[PredSpan]] = {}
    for doc, spans in preds_by_doc.items():
        remapped = remap_pred_spans(spans, mapping=label_map)
        if merge_person_names and doc in doc_text_by_name:
            remapped = merge_adjacent_person_names(remapped, text=doc_text_by_name[doc])
        out[doc] = remapped
    return out


def pred_rows_to_preds_by_doc(rows: List[Dict[str, Any]], *, task: str = "pii") -> Dict[str, List[PredSpan]]:
    from eval.predictors import OpenMedPredictor

    return OpenMedPredictor.preds_by_doc_from_rows(rows, task=task)
