from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Tuple

from eval.types import GoldSpan, PredSpan, overlap_len


MatchKind = Literal["type_overlap", "strict"]


@dataclass(frozen=True)
class MatchPair:
    gold: GoldSpan
    pred: PredSpan
    overlap: int


@dataclass(frozen=True)
class MatchOutput:
    kind: MatchKind
    tp: List[MatchPair]
    fp: List[PredSpan]
    fn: List[GoldSpan]
    # Confusions are diagnostic: overlap but different entity_id.
    confusion: Dict[str, Dict[str, int]]
    confused_pairs: List[Tuple[GoldSpan, PredSpan, int]]


def _doc_key(span) -> str:
    """Document a span belongs to: gold carries source_file, pred carries provenance["doc"]."""
    source_file = getattr(span, "source_file", None)
    if source_file:
        return str(source_file)
    provenance = getattr(span, "provenance", None) or {}
    return str(provenance.get("doc") or "")


def _bucket_by_entity_id(items):
    """Bucket by (doc, entity_id). Without the doc key, spans from different documents
    share offset ranges and can pair with each other, inventing true positives."""
    out: Dict[Tuple[str, str], list] = {}
    for it in items:
        out.setdefault((_doc_key(it), it.entity_id), []).append(it)
    return out


def _subsumed_gold_run(
    pred: PredSpan,
    golds: List[GoldSpan],
    *,
    require_strict: bool,
) -> List[GoldSpan]:
    """Gold spans that a single pred legitimately covers.

    Gold annotates names token by token ("James", "Michael", "O'Connor" are three spans)
    because it was derived from OpenMed's first_name/last_name schema, while the pipeline
    emits one merged span. Pairing 1:1 would match the merged span to one token and turn
    its siblings into false negatives. Strict additionally requires the pred to begin and
    end exactly on the run, so an over-broad span still fails it.
    """
    covered = sorted(
        (g for g in golds if pred.start <= g.start and g.end <= pred.end),
        key=lambda g: (g.start, g.end),
    )
    if len(covered) < 2:
        return []
    if require_strict and not (covered[0].start == pred.start and covered[-1].end == pred.end):
        return []
    return covered


def _greedy_pair_by_max_overlap(
    golds: List[GoldSpan],
    preds: List[PredSpan],
    *,
    require_strict: bool,
) -> Tuple[List[MatchPair], List[GoldSpan], List[PredSpan]]:
    if not golds and not preds:
        return [], [], []

    pairs: List[MatchPair] = []
    consumed_gold: set = set()
    consumed_pred: set = set()

    # Widest pred first: a span covering several gold tokens of the same entity takes the
    # whole run, so merging fragments is not scored as misses.
    for p in sorted(preds, key=lambda s: s.start - s.end):
        run = _subsumed_gold_run(
            p,
            [g for g in golds if id(g) not in consumed_gold],
            require_strict=require_strict,
        )
        if not run:
            continue
        consumed_pred.add(id(p))
        for g in run:
            consumed_gold.add(id(g))
            pairs.append(
                MatchPair(gold=g, pred=p, overlap=overlap_len(g.start, g.end, p.start, p.end))
            )

    remaining_gold = [g for g in golds if id(g) not in consumed_gold]
    remaining_pred = [p for p in preds if id(p) not in consumed_pred]

    # Greedy: repeatedly take the best remaining (gold,pred) overlap.
    while remaining_gold and remaining_pred:
        best_i = None
        best_j = None
        best_ov = 0
        for i, g in enumerate(remaining_gold):
            for j, p in enumerate(remaining_pred):
                if require_strict and not (p.start == g.start and p.end == g.end):
                    continue
                ov = overlap_len(g.start, g.end, p.start, p.end)
                if ov <= 0:
                    continue
                if ov > best_ov:
                    best_ov = ov
                    best_i = i
                    best_j = j

        if best_i is None or best_j is None:
            break

        g = remaining_gold.pop(best_i)
        p = remaining_pred.pop(best_j)
        pairs.append(MatchPair(gold=g, pred=p, overlap=best_ov))

    return pairs, remaining_gold, remaining_pred


def match_type_overlap(
    gold: List[GoldSpan],
    pred: List[PredSpan],
    *,
    kind: MatchKind = "type_overlap",
) -> MatchOutput:
    """Match spans with same entity_id using overlap>=1, one-to-one greedy pairing."""
    gold_by = _bucket_by_entity_id(gold)
    pred_by = _bucket_by_entity_id(pred)

    tp: List[MatchPair] = []
    fn: List[GoldSpan] = []
    fp: List[PredSpan] = []

    for key in sorted(set(gold_by.keys()) | set(pred_by.keys())):
        pairs, rem_gold, rem_pred = _greedy_pair_by_max_overlap(
            gold_by.get(key, []),
            pred_by.get(key, []),
            require_strict=False,
        )
        tp.extend(pairs)
        fn.extend(rem_gold)
        fp.extend(rem_pred)

    confusion, confused_pairs = compute_confusions(gold, pred)
    return MatchOutput(
        kind=kind,
        tp=tp,
        fp=fp,
        fn=fn,
        confusion=confusion,
        confused_pairs=confused_pairs,
    )


def match_strict(
    gold: List[GoldSpan],
    pred: List[PredSpan],
) -> MatchOutput:
    """Match spans with same entity_id and exact start/end, one-to-one greedy pairing."""
    gold_by = _bucket_by_entity_id(gold)
    pred_by = _bucket_by_entity_id(pred)

    tp: List[MatchPair] = []
    fn: List[GoldSpan] = []
    fp: List[PredSpan] = []

    for key in sorted(set(gold_by.keys()) | set(pred_by.keys())):
        pairs, rem_gold, rem_pred = _greedy_pair_by_max_overlap(
            gold_by.get(key, []),
            pred_by.get(key, []),
            require_strict=True,
        )
        tp.extend(pairs)
        fn.extend(rem_gold)
        fp.extend(rem_pred)

    confusion, confused_pairs = compute_confusions(gold, pred)
    return MatchOutput(
        kind="strict",
        tp=tp,
        fp=fp,
        fn=fn,
        confusion=confusion,
        confused_pairs=confused_pairs,
    )


def compute_confusions(
    gold: List[GoldSpan],
    pred: List[PredSpan],
    *,
    max_pairs: int = 5000,
) -> Tuple[Dict[str, Dict[str, int]], List[Tuple[GoldSpan, PredSpan, int]]]:
    """Return diagnostic label confusions for overlapping spans with different entity_id."""
    confusion: Dict[str, Dict[str, int]] = {}
    pairs: List[Tuple[GoldSpan, PredSpan, int]] = []

    for g in gold:
        for p in pred:
            if g.entity_id == p.entity_id or _doc_key(g) != _doc_key(p):
                continue
            ov = overlap_len(g.start, g.end, p.start, p.end)
            if ov <= 0:
                continue
            confusion.setdefault(g.entity_id, {})
            confusion[g.entity_id][p.entity_id] = confusion[g.entity_id].get(p.entity_id, 0) + 1
            if len(pairs) < max_pairs:
                pairs.append((g, p, ov))

    return confusion, pairs

