from __future__ import annotations

import argparse
from pathlib import Path

from eval.compare_common import (
    NER_SENSITIVE_SUFFIXES as _NER_SENSITIVE,
    backend_label,
    delta_str,
    entity_suffix,
    llm_total,
    load_report,
    ner_infer_total,
    per_entity_f1_deltas,
    resolve_report,
)

_LLM_SENSITIVE = frozenset(
    {
        "person_names",
        "physician_names",
        "city",
        "state",
        "street_address",
        "relative_date_expressions",
        "hospital_names",
        "genomic_variants",
        "health_plan_beneficiary_number",
        "passport_number",
        "drivers_license_number",
    }
)


def _compare_vs_baseline(run_path: Path, baseline_path: Path, top: int) -> None:
    run = load_report(run_path)
    base = load_report(baseline_path)

    run_micro = run["headline"]["micro"]
    base_micro = base["headline"]["micro"]
    run_label = backend_label(run)

    print(f"Run:      {run.get('run_id', run_path)} [{run_label}]")
    print(f"Baseline: {baseline_path}")
    print()
    print("Headline (type+overlap)")
    print(f"  micro_f1 : {run_micro['f1']:.3f}  ({delta_str(run_micro['f1'], base_micro['f1'])} vs baseline)")
    print(f"  micro_p  : {run_micro['precision']:.3f}  ({delta_str(run_micro['precision'], base_micro['precision'])})")
    print(f"  micro_r  : {run_micro['recall']:.3f}  ({delta_str(run_micro['recall'], base_micro['recall'])})")
    print()

    deltas = per_entity_f1_deltas(run, base)
    print(f"Top {top} per-entity F1 deltas")
    for _, delta, support, eid, rf1, bf1 in deltas[:top]:
        sign = "+" if delta >= 0 else ""
        print(f"  {sign}{delta:+.3f}  {rf1:.3f} vs {bf1:.3f}  support={support:>3}  {eid}")


def _compare_runs(path_a: Path, path_b: Path, *, top: int, min_delta: float) -> None:
    report_a = load_report(path_a)
    report_b = load_report(path_b)

    label_a = backend_label(report_a)
    label_b = backend_label(report_b)
    id_a = report_a.get("run_id", path_a.parent.name)
    id_b = report_b.get("run_id", path_b.parent.name)

    micro_a = report_a["headline"]["micro"]
    micro_b = report_b["headline"]["micro"]
    strict_a = report_a["strict"]["micro"]
    strict_b = report_b["strict"]["micro"]

    col_w = max(len(id_a), len(id_b), 26)

    def row(label: str, va: float, vb: float) -> None:
        print(f"  {label:<22}  {va:.3f}  {vb:.3f}  {delta_str(vb, va)}")

    print(f"{'':24}  {id_a[:col_w]:<{col_w}}  {id_b[:col_w]}")
    print(f"{'':24}  [{label_a}]  [{label_b}]")
    print()
    print("── Headline ─────────────────────────────────────")
    row("micro F1", micro_a["f1"], micro_b["f1"])
    row("micro precision", micro_a["precision"], micro_b["precision"])
    row("micro recall", micro_a["recall"], micro_b["recall"])
    row("strict micro F1", strict_a["f1"], strict_b["f1"])
    print()

    infer_a = ner_infer_total(report_a)
    infer_b = ner_infer_total(report_b)
    llm_a = llm_total(report_a)
    llm_b = llm_total(report_b)
    if infer_a > 0.0 or infer_b > 0.0:
        print("── Latency ──────────────────────────────────────")
        row("NER infer total (s)", infer_a, infer_b)
        if llm_a is not None or llm_b is not None:
            row("LLM total (s)", llm_a or 0.0, llm_b or 0.0)
        print()

    pe_a = report_a.get("per_entity") or {}
    pe_b = report_b.get("per_entity") or {}
    all_eids = sorted(set(pe_a.keys()) | set(pe_b.keys()))

    rows_all = []
    rows_ner = []
    rows_llm = []
    for eid in all_eids:
        ra = pe_a.get(eid) or {}
        rb = pe_b.get(eid) or {}
        f1a = float(ra.get("f1", 0.0))
        f1b = float(rb.get("f1", 0.0))
        support = int(ra.get("support") or rb.get("support") or 0)
        delta = f1b - f1a
        entry = (abs(delta), delta, support, eid, f1a, f1b)
        rows_all.append(entry)
        short = entity_suffix(eid)
        if short in _NER_SENSITIVE:
            rows_ner.append(entry)
        if short in _LLM_SENSITIVE:
            rows_llm.append(entry)

    rows_all.sort(reverse=True)
    rows_ner.sort(reverse=True)
    rows_llm.sort(reverse=True)

    def print_entity_table(title: str, rows: list, limit: int) -> None:
        print(f"── {title} {'─' * max(0, 47 - len(title))}")
        print(f"  {'entity':<48}  {'A':>6}  {'B':>6}  {'Δ(B-A)':>8}  support")
        for _, delta, support, eid, f1a, f1b in rows[:limit]:
            sign = "+" if delta >= 0 else ""
            print(f"  {eid:<48}  {f1a:.3f}  {f1b:.3f}  {sign}{delta:+.3f}   {support:>3}")
        print()

    print_entity_table(f"Per-entity F1 (top {top} by |Δ|)", rows_all, top)

    meaningful_ner = [row for row in rows_ner if abs(row[1]) >= min_delta]
    if meaningful_ner:
        print_entity_table(
            f"NER-sensitive entities (|Δ| ≥ {min_delta:.2f})",
            meaningful_ner,
            len(meaningful_ner),
        )
    else:
        print(f"── NER-sensitive entities: no differences ≥ {min_delta:.2f} ──")
        print()

    attr_a = report_a.get("llm_attribution")
    attr_b = report_b.get("llm_attribution")
    if attr_a or attr_b:
        print("── LLM attribution ──────────────────────────────")
        for label, attr in ((id_a, attr_a), (id_b, attr_b)):
            if attr:
                print(
                    f"  [{label}] llm_tp={attr['llm_tp']} llm_fp={attr['llm_fp']} "
                    f"llm_prec={attr['llm_precision']:.3f} "
                    f"recall_contrib={attr['llm_recall_contribution']:.3f} "
                    f"net_f1_gain={attr['llm_net_f1_gain']:+.3f}"
                )
            else:
                print(f"  [{label}] no LLM stage")
        print()

        meaningful_llm = [row for row in rows_llm if abs(row[1]) >= min_delta]
        if meaningful_llm:
            print_entity_table(
                f"LLM-sensitive entities (|Δ| ≥ {min_delta:.2f})",
                meaningful_llm,
                len(meaningful_llm),
            )
        else:
            print(f"── LLM-sensitive entities: no differences ≥ {min_delta:.2f} ──")
            print()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Compare eval runs. "
            "One positional arg: compare run vs baseline. "
            "Two positional args: compare run A vs run B side-by-side."
        )
    )
    ap.add_argument("run_a", help="Run ID, runs folder, or path to report.json.")
    ap.add_argument("run_b", nargs="?", default=None, help="Second run for side-by-side comparison.")
    ap.add_argument(
        "--baseline",
        default="eval/baselines/unstructured_baseline.json",
        help="Baseline report.json path (single-run mode).",
    )
    ap.add_argument("--top", type=int, default=30, help="Top N entities by |Δ F1|.")
    ap.add_argument(
        "--min-delta",
        type=float,
        default=0.02,
        help="Minimum |Δ F1| for NER-sensitive section.",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    path_a = resolve_report(args.run_a, repo_root)

    if args.run_b is not None:
        path_b = resolve_report(args.run_b, repo_root)
        _compare_runs(path_a, path_b, top=args.top, min_delta=args.min_delta)
    else:
        baseline_path = (repo_root / args.baseline).resolve()
        _compare_vs_baseline(path_a, baseline_path, top=args.top)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
