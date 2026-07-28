from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from eval.matchers import MatchOutput
from eval.metrics import EntityMetrics, macro_from_entity_metrics, micro_from_entity_metrics
from eval.types import GoldSpan, PredSpan

# Above this many FP+FN rows, skip inline lists in report.md and point to detail files.
DETAIL_LIST_INLINE_MAX = 80


@dataclass(frozen=True)
class ReportContext:
    """Inputs for :func:`build_report_dict`."""

    run_id: str
    git_sha: Optional[str]
    config: Dict[str, Any]
    matcher: MatchOutput
    strict: MatchOutput
    per_entity: Dict[str, EntityMetrics]
    per_entity_strict: Dict[str, EntityMetrics]
    per_doc: Dict[str, Any]
    rescue: Dict[str, Any]
    timing: Optional[Dict[str, Any]] = None
    llm_attribution: Optional[Dict[str, Any]] = None
    winner_kind_breakdown: Optional[Dict[str, Any]] = None


def _fmt(x: float) -> str:
    return f"{x:.3f}"


def _fmt_ms(x: float) -> str:
    return f"{x:.1f}"


def _fmt_sec(x: float) -> str:
    return f"{x:.4f}"


def entity_display_name(entity_id: str) -> str:
    if "::" in entity_id:
        return entity_id.split("::", 1)[1]
    return entity_id


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def _snippet(text: str, start: int, end: int, *, window: int = 60) -> str:
    a = max(0, start - window)
    b = min(len(text), end + window)
    s = text[a:b].replace("\n", "\\n")
    return s


def build_report_dict(ctx: ReportContext) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "run_id": ctx.run_id,
        "git_sha": ctx.git_sha,
        "config": ctx.config,
        "headline": {
            "matcher": ctx.matcher.kind,
            "micro": asdict(micro_from_entity_metrics(ctx.per_entity)),
            "macro": asdict(macro_from_entity_metrics(ctx.per_entity)),
        },
        "strict": {
            "micro": asdict(micro_from_entity_metrics(ctx.per_entity_strict)),
            "macro": asdict(macro_from_entity_metrics(ctx.per_entity_strict)),
        },
        "per_entity": {
            eid: {
                "tp": m.counts.tp,
                "fp": m.counts.fp,
                "fn": m.counts.fn,
                "support": m.counts.support,
                "precision": m.prf1.precision,
                "recall": m.prf1.recall,
                "f1": m.prf1.f1,
            }
            for eid, m in ctx.per_entity.items()
        },
        "per_entity_strict": {
            eid: {
                "tp": m.counts.tp,
                "fp": m.counts.fp,
                "fn": m.counts.fn,
                "support": m.counts.support,
                "precision": m.prf1.precision,
                "recall": m.prf1.recall,
                "f1": m.prf1.f1,
            }
            for eid, m in ctx.per_entity_strict.items()
        },
        "confusion": ctx.matcher.confusion,
        "rescue": ctx.rescue,
        "per_doc": ctx.per_doc,
    }
    if ctx.timing is not None:
        out["timing"] = ctx.timing
    if ctx.llm_attribution is not None:
        out["llm_attribution"] = ctx.llm_attribution
    if ctx.winner_kind_breakdown is not None:
        out["winner_kind_breakdown"] = ctx.winner_kind_breakdown
    return out


def format_confusion_sections(conf: Dict[str, Dict[str, int]]) -> tuple[str, str]:
    """
    Build markdown for label confusion (overlapping spans with wrong predicted type).

    Returns:
        (intro + matrix table markdown, long-form table markdown)
    """
    if not conf:
        return "- _(none)_\n", ""

    pred_ids: set[str] = set()
    for inner in conf.values():
        pred_ids.update(inner.keys())
    gold_ids = sorted(conf.keys())
    pred_ids_sorted = sorted(pred_ids)

    lines: List[str] = []
    lines.append(
        "Overlapping span pairs where **gold label ≠ predicted label** "
        "(off-diagonal confusion only; correct matches are not shown here)."
    )
    lines.append("")

    # Wide matrix: rows = gold, cols = predicted (short names in headers).
    pred_headers = [entity_display_name(p).replace("|", "\\|") for p in pred_ids_sorted]
    lines.append("| Gold \\ Pred | " + " | ".join(f"**{h}**" for h in pred_headers) + " |")
    lines.append("|" + "|".join(["---"] * (1 + len(pred_ids_sorted))) + "|")
    for g in gold_ids:
        g_short = entity_display_name(g).replace("|", "\\|")
        row: List[str] = [f"**{g_short}**"]
        inner = conf.get(g, {})
        for p in pred_ids_sorted:
            c = int(inner.get(p, 0) or 0)
            row.append(str(c) if c else "")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("*Full `entity_id` keys appear in the long-form table below.*")
    lines.append("")

    matrix_md = "\n".join(lines)

    # Long-form: sort by count descending
    pairs: List[tuple[int, str, str]] = []
    for g, inner in sorted(conf.items()):
        for p, c in sorted(inner.items(), key=lambda t: -t[1]):
            ci = int(c)
            if ci > 0:
                pairs.append((ci, g, p))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))

    lf: List[str] = []
    lf.append("### Confusion (long form)")
    lf.append("")
    lf.append("| count | gold (name) | predicted (name) |")
    lf.append("|---:|---|---|")
    for c, g, p in pairs:
        lf.append(f"| {c} | {entity_display_name(g)} | {entity_display_name(p)} |")
    lf.append("")
    long_md = "\n".join(lf)
    return matrix_md, long_md


def _fp_item_md(p: PredSpan, doc_text_by_name: Dict[str, str]) -> List[str]:
    doc = p.provenance.get("doc") if p.provenance else None
    doc_text = doc_text_by_name.get(doc or "", "")
    snip = _snippet(doc_text, p.start, p.end) if doc_text else p.text.replace("\n", "\\n")
    out = [
        f"- **Predicted label:** `{p.entity_id}`",
        f"  - **Source file:** `{doc}`" if doc else "  - **Source file:** _(unknown)_",
        f"  - **Confidence:** {_fmt(p.confidence)}",
        f"  - **Winner kind:** `{p.winner_kind}`" if p.winner_kind else "  - **Winner kind:** _(unknown)_",
        f"  - **Offsets:** {p.start}–{p.end}",
        f"  - **Span text:** {p.text!r}",
        f"  - **Excerpt:** {snip!r}",
    ]
    if p.rescue_applied:
        out.append(f"  - **Rescue:** `{p.original_entity_id}` → `{p.entity_id}`")
    return out


def _fn_item_md(g: GoldSpan, doc_text_by_name: Dict[str, str]) -> List[str]:
    doc = g.source_file or ""
    doc_text = doc_text_by_name.get(doc, "")
    snip = (
        _snippet(doc_text, g.start, g.end)
        if doc_text
        else g.text.replace("\n", "\\n")
    )
    return [
        f"- **Gold label:** `{g.entity_id}`",
        f"  - **Source file:** `{doc}`" if doc else "  - **Source file:** _(unknown)_",
        "  - **Winner kind:** _(n/a — no prediction for this gold span)_",
        f"  - **Offsets:** {g.start}–{g.end}",
        f"  - **Span text:** {g.text!r}",
        f"  - **Excerpt:** {snip!r}",
    ]


def build_false_positives_md(
    fp_list: Sequence[PredSpan],
    doc_text_by_name: Dict[str, str],
    *,
    run_id: str,
) -> str:
    lines: List[str] = [
        f"# False positives ({run_id})",
        "",
        "Each item lists **Winner kind**: which merge hypothesis won for that span "
        "(`deterministic`, `ner`, or `context_candidate`). "
        "This file is created once per eval run; open the latest folder under `eval/runs/` "
        "or re-run `python -m eval.runner` to regenerate.",
        "",
    ]
    by_eid: Dict[str, List[PredSpan]] = defaultdict(list)
    for p in fp_list:
        by_eid[p.entity_id].append(p)
    for eid in sorted(by_eid.keys()):
        lines.append(f"## `{eid}` ({entity_display_name(eid)}) — {len(by_eid[eid])} item(s)")
        lines.append("")
        for p in sorted(by_eid[eid], key=lambda x: (-x.confidence, x.start)):
            lines.extend(_fp_item_md(p, doc_text_by_name))
            lines.append("")
    if not fp_list:
        lines.append("_(none)_")
        lines.append("")
    return "\n".join(lines)


def build_false_negatives_md(
    fn_list: Sequence[GoldSpan],
    doc_text_by_name: Dict[str, str],
    *,
    run_id: str,
) -> str:
    lines: List[str] = [
        f"# False negatives ({run_id})",
        "",
        "There is no model **Winner kind** for a missed gold span; each item shows **n/a** "
        "below. This file is created once per eval run; use the latest `eval/runs/<id>/` "
        "or re-run `python -m eval.runner`.",
        "",
    ]
    by_eid: Dict[str, List[GoldSpan]] = defaultdict(list)
    for g in fn_list:
        by_eid[g.entity_id].append(g)
    for eid in sorted(by_eid.keys()):
        lines.append(f"## `{eid}` ({entity_display_name(eid)}) — {len(by_eid[eid])} item(s)")
        lines.append("")
        for g in sorted(by_eid[eid], key=lambda x: (x.source_file or "", x.start)):
            lines.extend(_fn_item_md(g, doc_text_by_name))
            lines.append("")
    if not fn_list:
        lines.append("_(none)_")
        lines.append("")
    return "\n".join(lines)


def build_rescues_md(
    rescues: Sequence[PredSpan],
    doc_text_by_name: Dict[str, str],
    *,
    run_id: str,
) -> str:
    lines: List[str] = [
        f"# Rescues (`rescue_applied`) ({run_id})",
        "",
        "Each row includes **Winner kind** for the final prediction after merge. "
        "This file is created once per eval run; use the latest `eval/runs/<id>/` "
        "or re-run `python -m eval.runner`.",
        "",
    ]
    for p in sorted(rescues, key=lambda x: (x.provenance.get("doc", ""), x.start)):
        doc = p.provenance.get("doc") if p.provenance else None
        doc_text = doc_text_by_name.get(doc or "", "")
        snip = _snippet(doc_text, p.start, p.end) if doc_text else p.text.replace("\n", "\\n")
        lines.append(f"- **From** `{p.original_entity_id}` **→** `{p.entity_id}`")
        lines.append(f"  - **Source file:** `{doc}`" if doc else "  - **Source file:** _(unknown)_")
        lines.append(f"  - **Confidence:** {_fmt(p.confidence)}")
        lines.append(
            f"  - **Winner kind:** `{p.winner_kind}`" if p.winner_kind else "  - **Winner kind:** _(unknown)_"
        )
        lines.append(f"  - **Offsets:** {p.start}–{p.end}")
        lines.append(f"  - **Span text:** {p.text!r}")
        lines.append(f"  - **Excerpt:** {snip!r}")
        lines.append("")
    if not rescues:
        lines.append("_(none)_")
        lines.append("")
    return "\n".join(lines)


def build_report_md(
    *,
    report: Dict[str, Any],
    per_entity: Dict[str, EntityMetrics],
    per_doc: Dict[str, Any],
    all_fp: List[PredSpan],
    all_fn: List[GoldSpan],
    doc_text_by_name: Dict[str, str],
    artifact_names: Dict[str, str],
    max_inline_examples: int = 15,
) -> str:
    head_micro = report["headline"]["micro"]
    head_macro = report["headline"]["macro"]
    strict_micro = report["strict"]["micro"]
    timing = report.get("timing") or {}
    per_doc_timing = timing.get("per_doc") or []

    lines: List[str] = []
    lines.append(f"# Eval report {report['run_id']}")
    if report.get("git_sha"):
        lines.append(f"- git: `{report['git_sha']}`")
    cfg = report.get("config") or {}
    ner_backend = cfg.get("ner_backend", "spacy")
    ner_model = cfg.get("ner_model")
    backend_label = f"`{ner_backend}`" + (f" (`{ner_model}`)" if ner_model else "")
    lines.append(f"- NER backend: {backend_label}")
    llm_backend = cfg.get("llm_backend")
    if llm_backend:
        llm_model = cfg.get("llm_model", "")
        llm_coverage = cfg.get("llm_coverage", "gaps")
        lines.append(f"- LLM backend: `{llm_backend}` model=`{llm_model}` coverage=`{llm_coverage}`")
    lines.append("")

    # Timing first (highlighted)
    lines.append("## Timing")
    lines.append("")
    if timing.get("batched"):
        lines.append(
            f"**Batched `classify_texts`**: {_fmt_sec(float(timing.get('batch_wall_s', 0.0)))}s "
            f"over {timing.get('batch_docs', 0)} documents "
            f"({_fmt_ms(float(timing.get('batch_ms_per_doc', 0.0)))} ms/doc, "
            f"{_fmt_ms(float(timing.get('batch_ms_per_1k_chars', 0.0)))} ms/1k chars). "
            "NER runs as one forward pass for the whole batch, so there is no per-document "
            "stage breakdown — re-run with `--no-batched` for that."
        )
        lines.append("")
    if per_doc_timing:
        lines.append(
            "**Per-document `classify_text` wall time** (first row often includes cold start: "
            "ontology load + first NER model load when enabled)."
        )
        lines.append("")
        has_llm = any(row.get("llm_s", 0.0) > 0 for row in per_doc_timing)
        timing_header = (
            "| doc | idx | chars | wall (s) | ms / 1k chars | "
            "configs (s) | deterministic (s) | NER total (s) | NER load (s) | NER infer (s) | merge (s)"
        )
        timing_sep = "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:"
        if has_llm:
            timing_header += " | LLM (s)"
            timing_sep += "|---:"
        lines.append(timing_header + " |")
        lines.append(timing_sep + "|")
        for row in per_doc_timing:
            doc = row.get("doc", "")
            idx = row.get("doc_index", "")
            n = row.get("char_len", 0)
            w = float(row.get("wall_classify_s", 0.0))
            ms1k = float(row.get("ms_per_1k_chars", 0.0))
            st = row.get("stages") or {}
            line = (
                f"| `{doc}` | {idx} | {n} | {_fmt_sec(w)} | {_fmt_ms(ms1k)} | "
                f"{_fmt_sec(float(st.get('load_entity_configs_s', 0.0)))} | "
                f"{_fmt_sec(float(st.get('deterministic_s', 0.0)))} | "
                f"{_fmt_sec(float(st.get('ner_s', 0.0)))} | "
                f"{_fmt_sec(float(st.get('ner_nlp_acquire_s', 0.0)))} | "
                f"{_fmt_sec(float(st.get('ner_tokenize_infer_s', 0.0)))} | "
                f"{_fmt_sec(float(st.get('merge_contextual_s', 0.0)))}"
            )
            if has_llm:
                line += f" | {_fmt_sec(float(row.get('llm_s', 0.0)))}"
            lines.append(line + " |")
        lines.append("")
    else:
        lines.append("_(no timing rows)_")
        lines.append("")

    lines.append("## Metrics summary")
    lines.append("")
    lines.append(
        f"- **Micro F1** (type+overlap): **{_fmt(head_micro['f1'])}** — "
        f"P {_fmt(head_micro['precision'])} / R {_fmt(head_micro['recall'])}"
    )
    lines.append(
        f"- **Macro F1:** **{_fmt(head_macro['f1'])}** — "
        f"P {_fmt(head_macro['precision'])} / R {_fmt(head_macro['recall'])}"
    )
    lines.append(
        f"- **Strict micro F1:** **{_fmt(strict_micro['f1'])}** — "
        f"P {_fmt(strict_micro['precision'])} / R {_fmt(strict_micro['recall'])}"
    )
    lines.append("")
    lines.append("### Artifact files")
    lines.append("")
    for label, fname in sorted(artifact_names.items()):
        lines.append(f"- **{label}:** `{fname}`")
    lines.append("")

    lines.append("## Per-entity metrics (type+overlap)")
    lines.append("")
    lines.append("| entity_id | support | P | R | F1 | TP | FP | FN |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for eid, m in sorted(per_entity.items(), key=lambda t: (-t[1].counts.support, t[0])):
        lines.append(
            f"| `{eid}` | {m.counts.support} | {_fmt(m.prf1.precision)} | {_fmt(m.prf1.recall)} | "
            f"{_fmt(m.prf1.f1)} | {m.counts.tp} | {m.counts.fp} | {m.counts.fn} |"
        )
    lines.append("")

    lines.append("## Label confusion matrix (wrong-type overlaps)")
    lines.append("")
    conf = report.get("confusion") or {}
    matrix_part, long_part = format_confusion_sections(conf)
    lines.append(matrix_part)
    if long_part:
        lines.append(long_part)

    lines.append("## Per-document (micro, type+overlap)")
    lines.append("")
    lines.append("| doc | support | P | R | F1 |")
    lines.append("|---|---:|---:|---:|---:|")
    for doc, d in per_doc.items():
        lines.append(
            f"| `{doc}` | {d.get('support', 0)} | {_fmt(d.get('precision', 0.0))} | "
            f"{_fmt(d.get('recall', 0.0))} | {_fmt(d.get('f1', 0.0))} |"
        )
    lines.append("")

    total_err = len(all_fp) + len(all_fn)
    lines.append("## False positives / false negatives (samples)")
    lines.append("")
    if total_err <= DETAIL_LIST_INLINE_MAX:
        lines.append("### False positives")
        lines.append("")
        for p in all_fp[:max_inline_examples]:
            lines.extend(_fp_item_md(p, doc_text_by_name))
            lines.append("")
        if len(all_fp) > max_inline_examples:
            lines.append(f"_… and {len(all_fp) - max_inline_examples} more (see detail file)._")
            lines.append("")
        elif not all_fp:
            lines.append("- _(none)_")
            lines.append("")
        lines.append("### False negatives")
        lines.append("")
        for g in all_fn[:max_inline_examples]:
            lines.extend(_fn_item_md(g, doc_text_by_name))
            lines.append("")
        if len(all_fn) > max_inline_examples:
            lines.append(f"_… and {len(all_fn) - max_inline_examples} more (see detail file)._")
            lines.append("")
        elif not all_fn:
            lines.append("- _(none)_")
            lines.append("")
    else:
        lines.append(
            f"**{len(all_fp)}** false positives and **{len(all_fn)}** false negatives — "
            f"lists are in the detail markdown files (see Artifact files above)."
        )
        lines.append("")

    # Winner-kind breakdown
    wk = report.get("winner_kind_breakdown")
    if wk:
        lines.append("## Winner-kind breakdown")
        lines.append("")
        lines.append("| kind | TP | FP |")
        lines.append("|---|---:|---:|")
        for kind in sorted(wk.keys()):
            counts = wk[kind]
            lines.append(f"| `{kind}` | {counts.get('tp', 0)} | {counts.get('fp', 0)} |")
        lines.append("")

    # LLM attribution
    llm_attr = report.get("llm_attribution")
    if llm_attr:
        lines.append("## LLM attribution")
        lines.append("")
        lines.append(
            f"- **LLM TP** (spans found only by LLM): **{llm_attr['llm_tp']}**"
        )
        lines.append(f"- **LLM FP** (LLM hallucinations): **{llm_attr['llm_fp']}**")
        lines.append(f"- **LLM precision**: {llm_attr['llm_precision']:.3f}")
        lines.append(
            f"- **LLM recall contribution** (llm_tp / total_gold): "
            f"{llm_attr['llm_recall_contribution']:.3f}"
        )
        lines.append(
            f"- **Micro F1 with LLM**: {llm_attr['micro_f1_with_llm']:.3f} | "
            f"**without LLM**: {llm_attr['micro_f1_without_llm']:.3f} | "
            f"**net gain**: {llm_attr['llm_net_f1_gain']:+.3f}"
        )
        lines.append("")

    lines.append("## Rescue summary")
    lines.append("")
    rescue = report.get("rescue") or {}
    lines.append(f"- **rescue_applied** count: **{rescue.get('applied', 0)}**")
    lines.append(
        f"- **rescue_applied** on TP: {rescue.get('tp_after', 0)} | "
        f"on FP: {rescue.get('fp_after', 0)}"
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def predspan_to_json_obj(p: PredSpan) -> Dict[str, Any]:
    doc = p.provenance.get("doc") if p.provenance else None
    obj: Dict[str, Any] = {
        "doc": doc,
        "start": p.start,
        "end": p.end,
        "text": p.text,
        "entity_id": p.entity_id,
        "confidence": p.confidence,
        "winner_kind": p.winner_kind,
        "rescue_applied": p.rescue_applied,
        "original_entity_id": p.original_entity_id,
    }
    if p.confidence_llm is not None:
        obj["confidence_llm"] = p.confidence_llm
    return obj
