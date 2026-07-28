"""Show the sensitive-data-readiness report end to end, on real project data.

    python3 demo_scripts/readiness_report_demo.py                 # both, spaCy NER
    python3 demo_scripts/readiness_report_demo.py --skip-ner      # regex only (fast)
    python3 demo_scripts/readiness_report_demo.py --only structured --json
    python3 demo_scripts/readiness_report_demo.py --policy hipaa_safe_harbor
    python3 demo_scripts/readiness_report_demo.py --policy gdpr --execute-policy

Unstructured docs come from test_data/unstructured/; structured rows from the generated
eval fixtures in test_data/structured/.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from seiba_risk_scanner import SeibaScanner  # noqa: E402
from seiba_risk_scanner.assessment import (  # noqa: E402
    ReadinessAssessor,
    SensitiveDataReadinessReport,
    SeverityLevel,
    write_report,
)
from seiba_risk_scanner.assessment.utility import utility_loss  # noqa: E402

DOCS_DIR = _ROOT / "test_data" / "unstructured"
ROWS_FILE = _ROOT / "test_data" / "structured" / "patient_registry.json"
LOCAL_RUNS = Path(__file__).resolve().parent / "local_runs"
BAR = "=" * 78


def _render(report: SensitiveDataReadinessReport, title: str, record_noun: str) -> None:
    print(f"\n{BAR}\n{title}\n{BAR}")

    breakdown = report.exposure_breakdown
    uniqueness = "not measured" if breakdown.uniqueness is None else f"{breakdown.uniqueness:.0%}"
    print(f"\nEXPOSURE INDEX  {report.exposure_index}/100   (0 = nothing sensitive, 100 = maximally exposed)")
    print(f"  {breakdown.severity_share:.0%} of findings are high/critical; "
          f"{uniqueness} of {record_noun}s are re-identifiable [{breakdown.mode}]")
    if breakdown.critical_floor_applied:
        print("  floored: a critical finding exists, so exposure cannot read lower")
    print("  NOT a readiness verdict - whether this is acceptable depends on intended use.")

    print("\nSEVERITY")
    for level in reversed(list(SeverityLevel)):
        count = report.severity_histogram.get(level, 0)
        if count:
            print(f"  {level.value:9} {'#' * min(count, 40):<40} {count}")

    print("\nTOP ENTITIES BY RISK")
    ranked = sorted(report.per_entity.items(), key=lambda kv: -kv[1].mean_risk_score * kv[1].count)
    for entity_id, rollup in ranked[:8]:
        tags = ",".join(t.value for t in rollup.compliance_tags) or "-"
        print(f"  {entity_id.split('::')[-1][:34]:36} n={rollup.count:<4} "
              f"worst={rollup.max_level.value:<8} mean={rollup.mean_risk_score:.2f}  {tags}")

    print(f"\nRISKIEST {record_noun.upper()}S")
    riskiest = sorted(report.per_record.items(), key=lambda kv: -kv[1].risk_mass)
    for label, profile in riskiest[:5]:
        flag = " SINGLETON" if profile.is_singleton else ""
        print(f"  {label:24} risk_mass={profile.risk_mass:6.2f}  findings={profile.finding_count:<4} "
              f"strong_types={profile.strong_identifier_types}  worst={profile.worst_level.value}{flag}")

    print("\nHIPAA SAFE HARBOR (18 identifiers)")
    found = [(i, s) for i, s in report.hipaa_checklist.items() if s.finding_count]
    for identifier, stat in found:
        print(f"  [x] {identifier.value:32} {stat.finding_count:<5} {', '.join(stat.entities)}")
    missing = [i.value for i, s in report.hipaa_checklist.items() if not s.finding_count]
    print(f"  [ ] not found ({len(missing)}): {', '.join(missing)}")

    print("\nCOMPLIANCE")
    for regulation, stat in report.compliance_summary.items():
        print(f"  {regulation.value:6} {stat.count:<5} findings, worst={stat.max_level.value}")

    reid = report.reidentification
    print("\nRE-IDENTIFICATION")
    if reid is None:
        print(f"  not measured - needs several {record_noun}s to compare against")
    else:
        print(f"  k_min={reid.k_min}  singletons={reid.singleton_count}/{reid.record_count}  "
              f"below k={reid.k_threshold}: {reid.records_below_k_threshold}")
        print(f"  grouped on: {', '.join(reid.quasi_identifiers) or '-'}"
              f"  | protecting: {', '.join(reid.sensitive_attributes) or '-'}")

    plan = report.policy_plan
    if plan is not None:
        mode = "executed" if plan.executed else "resolve-only"
        print(f"\nPOLICY PLAN ({plan.policy_name}, {mode})")
        print(f"  exact={plan.exact_count}  class_fallback={plan.class_fallback_count}  "
              f"neutral_keep={plan.neutral_keep_count}")
        for action, count in plan.action_histogram.items():
            print(f"  {action:16} {count}")
        for record in plan.records[:5]:
            fb = f"  fallback={record.execute_fallback}" if record.execute_fallback else ""
            rep = f"  → {record.replacement!r}" if record.replacement is not None else ""
            print(f"  {record.entity:24} {record.action:8} [{record.source}]{fb}{rep}")
            print(f"    {record.detail}")

    if plan is not None and plan.executed:
        print("\nSCRUB RESULT  (measured after applying the policy; lower is better)")
        if reid is not None and reid.reid_rate is not None:
            print(f"  residual re-identification={reid.reid_rate:.0%}   "
                  f"leakage={reid.leakage_rate:.0%}")
        util = utility_loss(plan.records)
        if util is not None:
            by = "  ".join(f"{cls}={loss:.0%}" for cls, loss in sorted(util.by_data_class.items()))
            print(f"  utility loss={util.overall:.0%}   (0 = all analytic value kept, "
                  "100 = all destroyed)")
            print(f"    by data_class: {by}")

    print(f"\nREVIEW QUEUE ({len(report.review_queue)} need a human)")
    for finding in report.review_queue[:5]:
        print(f"  {finding.assessment.level.value:9} {finding.detection.entity:26} "
              f"'{finding.detection.text[:28]}'  conf={finding.assessment.confidence:.2f}")

    if report.findings:
        worst = max(report.findings, key=lambda f: f.assessment.risk_score)
        print(f"\nWHY: '{worst.detection.text[:32]}' scored "
              f"{worst.assessment.risk_score:.2f} ({worst.assessment.level.value})")
        for rule in worst.assessment.rule_trace:
            factor = f"  x{rule.factor:.2f}" if rule.factor is not None else ""
            print(f"  [{rule.source:13}] {rule.detail}{factor}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("unstructured", "structured"))
    parser.add_argument("--skip-ner", action="store_true", help="regex only; much faster")
    parser.add_argument("--docs", type=int, default=6, help="unstructured documents to scan")
    parser.add_argument("--rows", type=int, default=40, help="structured rows to scan")
    parser.add_argument("--json", action="store_true", help="dump the raw report as JSON")
    parser.add_argument("--md", action="store_true", help="write a readable Markdown report")
    parser.add_argument(
        "--policy",
        default="hipaa_safe_harbor",
        help="OpenMed policy profile (e.g. hipaa_safe_harbor, gdpr_pseudonymization); "
        "pass --policy '' to disable",
    )
    parser.add_argument(
        "--execute-policy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply resolved actions to produce replacements (no vault)",
    )
    args = parser.parse_args()

    scanner = SeibaScanner(skip_ner=args.skip_ner)
    assessor = ReadinessAssessor(policy=args.policy, execute_policy=args.execute_policy)
    reports = {}
    scopes = {}

    if args.only != "structured":
        paths = sorted(DOCS_DIR.glob("*.txt"))[: args.docs]
        texts = [p.read_text(encoding="utf-8", errors="ignore") for p in paths]
        total = len(list(DOCS_DIR.glob("*.txt")))
        scopes["unstructured"] = f"{len(texts)} of {total} documents in {DOCS_DIR.name}/"
        print(f"scanning {len(texts)} documents: {', '.join(p.stem for p in paths)}")
        reports["unstructured"] = assessor.assess(
            scanner.classify_texts(texts), labels=[p.name for p in paths]
        )
        _render(reports["unstructured"], f"UNSTRUCTURED - {len(texts)} documents", "document")

    if args.only != "unstructured":
        rows = json.loads(ROWS_FILE.read_text(encoding="utf-8"))[: args.rows]
        scopes["structured"] = f"{len(rows)} rows of {ROWS_FILE.name}"
        print(f"\nscanning {len(rows)} structured rows from {ROWS_FILE.name}")
        reports["structured"] = assessor.assess(
            scanner.classify_structured_text(rows),
            labels=[ROWS_FILE.name],
            health_context=True,  # patient_registry.json is health data
        )
        _render(reports["structured"], f"STRUCTURED - {len(rows)} rows", "row")

    if args.json or args.md:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for name, report in reports.items():
            written = write_report(
                report,
                LOCAL_RUNS,
                f"readiness_report_{name}_{stamp}",
                title=f"Sensitive Data Report - {name}",
                scope=scopes.get(name),
            )
            for path in written:
                print(f"wrote {path.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
