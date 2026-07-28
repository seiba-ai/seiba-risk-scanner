from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from eval.matchers import MatchOutput
from eval.types import PredSpan


@dataclass(frozen=True)
class PRF1:
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class Counts:
    tp: int
    fp: int
    fn: int
    support: int


@dataclass(frozen=True)
class EntityMetrics:
    entity_id: str
    counts: Counts
    prf1: PRF1


def _safe_div(n: float, d: float) -> float:
    return float(n) / float(d) if d else 0.0


def prf1_from_counts(tp: int, fp: int, fn: int) -> PRF1:
    p = _safe_div(tp, tp + fp)
    r = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * p * r, p + r) if (p + r) else 0.0
    return PRF1(precision=p, recall=r, f1=f1)


def entity_metrics_from_match(
    match: MatchOutput,
    *,
    entity_ids: Optional[Iterable[str]] = None,
) -> Dict[str, EntityMetrics]:
    """Compute per-entity tp/fp/fn and PRF1 for the provided match output."""
    allow = set(entity_ids) if entity_ids is not None else None

    tp_by: Dict[str, int] = {}
    fp_by: Dict[str, int] = {}
    fn_by: Dict[str, int] = {}
    support_by: Dict[str, int] = {}

    for pair in match.tp:
        eid = pair.gold.entity_id
        if allow is not None and eid not in allow:
            continue
        tp_by[eid] = tp_by.get(eid, 0) + 1
        support_by[eid] = support_by.get(eid, 0) + 1

    for g in match.fn:
        eid = g.entity_id
        if allow is not None and eid not in allow:
            continue
        fn_by[eid] = fn_by.get(eid, 0) + 1
        support_by[eid] = support_by.get(eid, 0) + 1

    for p in match.fp:
        eid = p.entity_id
        if allow is not None and eid not in allow:
            continue
        fp_by[eid] = fp_by.get(eid, 0) + 1

    out: Dict[str, EntityMetrics] = {}
    for eid in sorted(set(tp_by) | set(fp_by) | set(fn_by) | set(support_by)):
        tp = tp_by.get(eid, 0)
        fp = fp_by.get(eid, 0)
        fn = fn_by.get(eid, 0)
        support = support_by.get(eid, 0)
        out[eid] = EntityMetrics(
            entity_id=eid,
            counts=Counts(tp=tp, fp=fp, fn=fn, support=support),
            prf1=prf1_from_counts(tp, fp, fn),
        )
    return out


def micro_from_entity_metrics(per_entity: Dict[str, EntityMetrics]) -> PRF1:
    tp = sum(m.counts.tp for m in per_entity.values())
    fp = sum(m.counts.fp for m in per_entity.values())
    fn = sum(m.counts.fn for m in per_entity.values())
    return prf1_from_counts(tp, fp, fn)


def macro_from_entity_metrics(per_entity: Dict[str, EntityMetrics]) -> PRF1:
    ms = [m for m in per_entity.values() if m.counts.support > 0]
    if not ms:
        return PRF1(precision=0.0, recall=0.0, f1=0.0)
    return PRF1(
        precision=sum(m.prf1.precision for m in ms) / len(ms),
        recall=sum(m.prf1.recall for m in ms) / len(ms),
        f1=sum(m.prf1.f1 for m in ms) / len(ms),
    )


def llm_attribution_metrics(
    tp_pairs,
    fp_preds: List[PredSpan],
    fn_golds,
    all_gold,
) -> Dict[str, Any]:
    """Measures LLM-specific contribution: what did the LLM stage uniquely find or hallucinate?

    Returns:
        llm_tp: TP spans where winner_kind == "llm"
        llm_fp: FP spans where winner_kind == "llm"
        llm_precision: llm_tp / (llm_tp + llm_fp)
        llm_recall_contribution: llm_tp / total_gold_support (how much recall LLM adds)
        llm_net_f1_gain: micro F1 with LLM - micro F1 without LLM spans
    """
    llm_tp = sum(1 for pair in tp_pairs if pair.pred.winner_kind == "llm")
    llm_fp = sum(1 for p in fp_preds if p.winner_kind == "llm")
    llm_p = _safe_div(llm_tp, llm_tp + llm_fp)
    total_gold = len(list(all_gold))
    llm_recall_contrib = _safe_div(llm_tp, total_gold)

    # F1 without LLM: treat llm TPs as FNs and llm FPs as removed
    total_tp = len(list(tp_pairs))
    total_fp = len(fp_preds)
    total_fn = len(list(fn_golds))
    with_llm = prf1_from_counts(total_tp, total_fp, total_fn)
    without_llm = prf1_from_counts(total_tp - llm_tp, total_fp - llm_fp, total_fn + llm_tp)

    return {
        "llm_tp": llm_tp,
        "llm_fp": llm_fp,
        "llm_precision": round(llm_p, 4),
        "llm_recall_contribution": round(llm_recall_contrib, 4),
        "llm_net_f1_gain": round(with_llm.f1 - without_llm.f1, 4),
        "micro_f1_with_llm": round(with_llm.f1, 4),
        "micro_f1_without_llm": round(without_llm.f1, 4),
    }


def winner_kind_breakdown(tp_pairs, fp_preds: List[PredSpan]) -> Dict[str, Dict[str, int]]:
    """Count TP and FP spans by winner_kind."""
    tp_by: Dict[str, int] = {}
    fp_by: Dict[str, int] = {}
    for pair in tp_pairs:
        k = pair.pred.winner_kind or "unknown"
        tp_by[k] = tp_by.get(k, 0) + 1
    for p in fp_preds:
        k = p.winner_kind or "unknown"
        fp_by[k] = fp_by.get(k, 0) + 1
    all_kinds = sorted(set(tp_by) | set(fp_by))
    return {k: {"tp": tp_by.get(k, 0), "fp": fp_by.get(k, 0)} for k in all_kinds}


def rescue_diagnostics(tp_pairs, fp_preds: List[PredSpan]) -> Dict[str, Any]:
    """Summaries around `rescue_applied` (as exposed on CombinedDetectionRow)."""
    applied = 0
    tp_after = 0
    fp_after = 0
    original_miss_counts: Dict[str, int] = {}

    for pair in tp_pairs:
        if pair.pred.rescue_applied:
            applied += 1
            tp_after += 1
            if pair.pred.original_entity_id:
                original_miss_counts[pair.pred.original_entity_id] = (
                    original_miss_counts.get(pair.pred.original_entity_id, 0) + 1
                )

    for p in fp_preds:
        if p.rescue_applied:
            applied += 1
            fp_after += 1
            if p.original_entity_id:
                original_miss_counts[p.original_entity_id] = (
                    original_miss_counts.get(p.original_entity_id, 0) + 1
                )

    return {
        "applied": int(applied),
        "tp_after": int(tp_after),
        "fp_after": int(fp_after),
        # This is a proxy: “rescue changed label away from original deterministic label”.
        "original_entity_id_counts": dict(sorted(original_miss_counts.items(), key=lambda t: (-t[1], t[0]))),
    }

