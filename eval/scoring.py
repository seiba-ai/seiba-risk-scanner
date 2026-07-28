"""Shared gold-vs-prediction scoring helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Set

from eval.gold import load_gold_spans_loose
from eval.matchers import match_strict, match_type_overlap
from eval.metrics import entity_metrics_from_match, prf1_from_counts
from eval.types import GoldSpan, PredSpan

MatcherName = Literal["strict", "type_overlap"]


def _matcher(name: MatcherName):
    return match_strict if name == "strict" else match_type_overlap


def score_predictions(
    gold: List[GoldSpan],
    preds: List[PredSpan],
    *,
    entity_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Score flat gold/pred lists (Seiba eval path). Returns match objects + entity metrics."""
    allow: Optional[Set[str]] = set(entity_ids) if entity_ids is not None else None
    match = match_type_overlap(gold, preds)
    strict = match_strict(gold, preds)
    return {
        "match": match,
        "strict": strict,
        "per_entity": entity_metrics_from_match(match, entity_ids=allow),
        "per_entity_strict": entity_metrics_from_match(strict, entity_ids=allow),
    }


def score_gold_preds_by_doc(
    *,
    files: List[Path],
    gold_for_doc: Callable[[str], Optional[List[GoldSpan]]],
    preds_by_doc: Dict[str, List[PredSpan]],
    matcher_name: MatcherName,
) -> Dict[str, Any]:
    matcher = _matcher(matcher_name)
    tp_by: Dict[str, int] = {}
    fp_by: Dict[str, int] = {}
    fn_by: Dict[str, int] = {}
    sup_by: Dict[str, int] = {}
    false_positives: List[Dict[str, Any]] = []
    false_negatives: List[Dict[str, Any]] = []
    scored_docs = 0

    for path in files:
        gold = gold_for_doc(path.name)
        if gold is None:
            continue
        scored_docs += 1
        match = matcher(gold, preds_by_doc.get(path.name, []))
        for pair in match.tp:
            eid = pair.gold.entity_id
            tp_by[eid] = tp_by.get(eid, 0) + 1
            sup_by[eid] = sup_by.get(eid, 0) + 1
        for span in match.fn:
            fn_by[span.entity_id] = fn_by.get(span.entity_id, 0) + 1
            sup_by[span.entity_id] = sup_by.get(span.entity_id, 0) + 1
            false_negatives.append(
                {
                    "doc": path.name,
                    "entity_id": span.entity_id,
                    "text": span.text,
                    "start": span.start,
                    "end": span.end,
                }
            )
        for pred in match.fp:
            fp_by[pred.entity_id] = fp_by.get(pred.entity_id, 0) + 1
            false_positives.append(
                {
                    "doc": path.name,
                    "entity_id": pred.entity_id,
                    "text": pred.text,
                    "start": pred.start,
                    "end": pred.end,
                    "confidence": pred.confidence,
                }
            )

    per_entity: Dict[str, Any] = {}
    for eid in sorted(set(tp_by) | set(fp_by) | set(fn_by) | set(sup_by)):
        tp = tp_by.get(eid, 0)
        fp = fp_by.get(eid, 0)
        fn = fn_by.get(eid, 0)
        prf = prf1_from_counts(tp, fp, fn)
        per_entity[eid] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "support": sup_by.get(eid, 0),
            "precision": prf.precision,
            "recall": prf.recall,
            "f1": prf.f1,
        }

    tp_total = sum(value["tp"] for value in per_entity.values())
    fp_total = sum(value["fp"] for value in per_entity.values())
    fn_total = sum(value["fn"] for value in per_entity.values())
    micro = prf1_from_counts(tp_total, fp_total, fn_total)
    supported = [value for value in per_entity.values() if value["support"] > 0]
    macro = {
        "precision": sum(value["precision"] for value in supported) / len(supported) if supported else 0.0,
        "recall": sum(value["recall"] for value in supported) / len(supported) if supported else 0.0,
        "f1": sum(value["f1"] for value in supported) / len(supported) if supported else 0.0,
    }
    return {
        "scored_docs": scored_docs,
        "micro": {
            "precision": micro.precision,
            "recall": micro.recall,
            "f1": micro.f1,
            "tp": tp_total,
            "fp": fp_total,
            "fn": fn_total,
        },
        "macro": macro,
        "per_entity": per_entity,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def score_openmed_pii_predictions(
    *,
    pred_rows: List[Dict[str, Any]],
    gold_dir: Path,
    files: List[Path],
) -> Dict[str, Any]:
    from eval.openmed_clinical import OPENMED_CLINICAL_ENTITY_IDS
    from eval.predictors import OpenMedPredictor

    preds_by_doc = OpenMedPredictor.preds_by_doc_from_rows(pred_rows, task="pii")

    def gold_for_doc(fname: str) -> Optional[List[GoldSpan]]:
        return load_gold_spans_loose(
            gold_dir / f"{fname.replace('.txt', '')}.gold.jsonl",
            fname,
            exclude_entity_ids=OPENMED_CLINICAL_ENTITY_IDS,
        )

    return {
        "strict": score_gold_preds_by_doc(
            files=files,
            gold_for_doc=gold_for_doc,
            preds_by_doc=preds_by_doc,
            matcher_name="strict",
        ),
        "type_overlap": score_gold_preds_by_doc(
            files=files,
            gold_for_doc=gold_for_doc,
            preds_by_doc=preds_by_doc,
            matcher_name="type_overlap",
        ),
    }


def score_openmed_mapped_on_ontology_gold(
    *,
    pred_rows: List[Dict[str, Any]],
    gold_dir: Path,
    repo_root: Path,
    files: List[Path],
    map_path: Optional[Path] = None,
    merge_person_names: bool = True,
) -> Dict[str, Any]:
    from eval.gold import load_gold_jsonl
    from eval.openmed_mapping import remap_openmed_preds_by_doc, pred_rows_to_preds_by_doc

    preds_by_doc = pred_rows_to_preds_by_doc(pred_rows, task="pii")
    doc_text_by_name: Dict[str, str] = {}
    gold_cache: Dict[str, Optional[List[GoldSpan]]] = {}

    def gold_for_doc(fname: str) -> Optional[List[GoldSpan]]:
        if fname not in gold_cache:
            stem = fname.replace(".txt", "")
            gold_path = gold_dir / f"{stem}.gold.jsonl"
            if not gold_path.is_file():
                gold_cache[fname] = None
            else:
                doc = load_gold_jsonl(gold_path, repo_root=repo_root)
                doc_text_by_name[fname] = doc.text
                gold_cache[fname] = doc.spans
        return gold_cache[fname]

    for path in files:
        gold_for_doc(path.name)

    mapped_preds = remap_openmed_preds_by_doc(
        preds_by_doc,
        doc_text_by_name=doc_text_by_name,
        map_path=str(map_path) if map_path else None,
        merge_person_names=merge_person_names,
    )

    return {
        "strict": score_gold_preds_by_doc(
            files=files,
            gold_for_doc=gold_for_doc,
            preds_by_doc=mapped_preds,
            matcher_name="strict",
        ),
        "type_overlap": score_gold_preds_by_doc(
            files=files,
            gold_for_doc=gold_for_doc,
            preds_by_doc=mapped_preds,
            matcher_name="type_overlap",
        ),
        "mapping": {
            "map_path": str(map_path or "eval/label_maps/openmed_to_ontology.yaml"),
            "merge_person_names": merge_person_names,
            "gold_dir": str(gold_dir),
        },
    }


def score_openmed_clinical_predictions(
    *,
    pred_rows: List[Dict[str, Any]],
    gold_dir: Path,
    files: List[Path],
) -> Dict[str, Any]:
    from eval.openmed_clinical import OPENMED_CLINICAL_ENTITY_IDS
    from eval.predictors import OpenMedPredictor

    preds_by_doc = OpenMedPredictor.preds_by_doc_from_rows(pred_rows, task="clinical")

    def gold_for_doc(fname: str) -> Optional[List[GoldSpan]]:
        spans = load_gold_spans_loose(
            gold_dir / f"{fname.replace('.txt', '')}.gold.jsonl",
            fname,
            entity_ids=OPENMED_CLINICAL_ENTITY_IDS,
        )
        return spans or None

    return {
        "strict": score_gold_preds_by_doc(
            files=files,
            gold_for_doc=gold_for_doc,
            preds_by_doc=preds_by_doc,
            matcher_name="strict",
        ),
        "type_overlap": score_gold_preds_by_doc(
            files=files,
            gold_for_doc=gold_for_doc,
            preds_by_doc=preds_by_doc,
            matcher_name="type_overlap",
        ),
    }
