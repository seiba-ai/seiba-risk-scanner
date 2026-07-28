"""Render a report as Markdown.

Written to be read by someone who has never seen this tool: every number states its scale,
every column is named in words, and each section opens with what it is for.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

from seiba_risk_scanner.assessment.models import (
    SensitiveDataReadinessReport,
    SeverityLevel,
)

LEVEL_MEANING = {
    SeverityLevel.CRITICAL: "Names a specific person outright",
    SeverityLevel.HIGH: "Harmful on its own — a direct, financial, or health identifier",
    SeverityLevel.MEDIUM: "Harmless alone, but narrows down who someone is when combined with other fields",
    SeverityLevel.LOW: "Barely sensitive",
    SeverityLevel.INFO: "Not sensitive",
}
_ORDER = (
    SeverityLevel.CRITICAL,
    SeverityLevel.HIGH,
    SeverityLevel.MEDIUM,
    SeverityLevel.LOW,
    SeverityLevel.INFO,
)


def _table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> List[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


def _glossary(*pairs: Tuple[str, str]) -> List[str]:
    """Bulleted 'what each column means' key, so no reader has to infer a header."""
    return ["**Reading this table**", ""] + [f"- **{k}** — {v}" for k, v in pairs] + [""]


def _is_tabular(report: SensitiveDataReadinessReport) -> bool:
    """True when findings carry a column/key, i.e. this scan was rows-and-columns."""
    return any(
        (f.detection.provenance or {}).get("column") or (f.detection.provenance or {}).get("key")
        for f in report.findings
    )


def _reid_verdict(reid) -> Tuple[str, str]:
    """Headline share of records that can be singled out, plus a plain risk label."""
    share = reid.records_below_k_threshold / reid.record_count if reid.record_count else 0.0
    if reid.k_min >= reid.k_threshold:
        return f"{share:.0%}", "LOW RISK"
    if share > 0.5:
        return f"{share:.0%}", "CRITICAL"
    if share > 0.10:
        return f"{share:.0%}", "HIGH RISK"
    if share > 0.01:
        return f"{share:.0%}", "MODERATE RISK"
    return f"{share:.0%}", "LOW RISK"


def _deidentification_lines(reid, utility) -> List[str]:
    """Post-scrub section: what the policy left behind, and what it cost to get there.

    The rates need a record population (structured only); utility loss does not, so a text
    corpus still gets the cost half. Verdicts are worded from the score, not just printed.
    """
    rates = reid is not None and reid.reid_rate is not None
    if not rates and utility is None:
        return []

    lines = [
        "## De-identification strength (what the scrub left behind)",
        "",
        "The policy was applied, then the scrubbed data was compared back against the "
        "original. The first numbers say how *safe* the result is (lower is better); the "
        "last says how much of the data's structure survived (higher is better).",
        "",
    ]
    if rates:
        leak = reid.leakage_rate
        if leak <= 0:
            lines.append(
                "- **Residue left behind: 0% — clean.** No raw sensitive value survived; every "
                "direct identifier was removed as planned."
            )
        else:
            lines.append(
                f"- **Residue left behind: {leak:.0%} — must be fixed.** That share of records "
                "still carry a raw sensitive value the policy should have removed. This should "
                "reach 0 before sharing. *(A policy that swaps in realistic fake values, like "
                "GDPR pseudonymization, reads high here by design — a fake name still looks like "
                "a name sitting in the field.)*"
            )
        rate = reid.reid_rate
        if rate <= 0:
            lines.append(
                "- **Still re-identifiable: 0% — strong.** After scrubbing, no record can be "
                "singled out by the traits left behind."
            )
        elif rate <= 0.01:
            lines.append(
                f"- **Still re-identifiable: {rate:.1%} — acceptable.** At or under the ~1% "
                "commonly treated as de-identified, but confirm those few records are fine."
            )
        elif rate <= 0.10:
            lines.append(
                f"- **Still re-identifiable: {rate:.0%} — moderate risk.** Above the ~1% "
                "yardstick. Coarsen the traits left in place: round ages into bands, dates to "
                "month, geography to region."
            )
        else:
            lines.append(
                f"- **Still re-identifiable: {rate:.0%} — high risk, not de-identified.** Direct "
                "identifiers went, but ordinary fields (age, dates, geography) still fingerprint "
                "people. Coarsen or drop them before sharing."
            )
    if utility is not None:
        retained = 1.0 - utility.overall
        lines.append(
            f"- **Data properties retained: {retained:.0%}** across the "
            f"{utility.finding_count} values the policy rewrote. This is a **structural** "
            "measure, not a judgement about your analysis: it counts how many useful "
            "properties survived in the scrubbed values, nothing more. Whether that is enough "
            "depends entirely on what you plan to do with the data."
        )
        if utility.by_data_class:
            by = ", ".join(
                f"{cls.replace('_', ' ')} {1.0 - value:.0%}"
                for cls, value in sorted(utility.by_data_class.items(), key=lambda kv: kv[1])
            )
            lines.append(f"  - Retained by kind of data: {by}")
        lines += [
            "",
            "  *The three properties checked on each rewritten value: can it still be read "
            "(weight 0.2); can two different originals still be told apart, which is what "
            "joining and counting need (0.5); does it keep its original shape and format "
            "(0.3). Masking to `[EMAIL]` destroys all three, so a fully masked field retains "
            "0%. A realistic fake value keeps the last two. Only these weights are a "
            "judgement call — the three checks are measured on the real output.*",
            "",
            "  *Scope: measured only on the values the policy rewrote. Untouched columns and "
            "surrounding text are unaffected and are not in this number.*",
        ]
    lines += [
        "",
        "> Safety and usefulness pull against each other. Today the policy you picked fixes "
        "both numbers; choosing a gentler action per field is what a future optimizer will "
        "search for.",
        "",
    ]
    return lines


def to_markdown(
    report: SensitiveDataReadinessReport,
    title: str = "Sensitive Data Report",
    scope: Optional[str] = None,
    details_path: Optional[str] = None,
) -> str:
    """Render the report. ``details_path`` names the JSON companion holding every record."""
    lines: List[str] = [f"# {title}", ""]
    if scope:
        lines += [f"*Scope: {scope}.*", ""]
    breakdown = report.exposure_breakdown
    tabular = _is_tabular(report)

    lines += [
        "## Exposure index",
        "",
        f"# {report.exposure_index} / 100",
        "",
        "**0 means nothing sensitive was found. 100 means maximally exposed.**",
        "",
        "This is *not* a pass/fail grade. Whether this level of exposure is acceptable depends "
        "on what the data is for — a clinical registry is supposed to hold patient names. "
        "Use it to compare datasets, or to track one dataset over time.",
        "",
        "**How it was calculated**",
        "",
        f"- **{breakdown.severity_share:.0%}** of findings are high or critical severity",
    ]
    if breakdown.uniqueness is None:
        lines.append(
            f"- Re-identifiability was **not measured**: {breakdown.record_count} record(s) "
            f"scanned, below the minimum of {breakdown.min_population} needed to tell whether "
            "anyone actually stands out."
        )
    else:
        lines.append(
            f"- **{breakdown.uniqueness:.0%}** of the {breakdown.record_count} records are "
            f"re-identifiable (fewer than 5 records share their combination of traits)"
        )
    if breakdown.critical_floor_applied:
        lines.append(
            "- A **critical** finding exists, so the index is held at a floor — one "
            "re-identifiable person must not average away behind harmless findings."
        )
    lines += ["", f"*(method: {breakdown.mode})*", ""]

    review = len(report.review_queue)
    lines += [
        "## At a glance",
        "",
        "The size of the job: how much sensitive data was found, and where.",
        "",
        *_table(
            [
                ["Findings", str(len(report.findings))],
                ["Locations with findings", str(len(report.heatmap))],
                ["Records scanned", str(breakdown.record_count)],
                ["Findings needing human review", str(review)],
            ],
            ["", "Count"],
        ),
        "",
        *_glossary(
            ("Finding", "one sensitive value found in one place. One document mentioning the "
             "same patient's name 12 times gives 12 findings, not 1"
             if not tabular else
             "one sensitive value found in one cell. A table of 40 rows with 11 sensitive "
             "columns gives 440 findings, not 40"),
            ("Location", "the document a finding came from"
             if not tabular else "the column a finding sat in"),
            ("Record", "one whole document — documents are counted as one record each, since "
             "each is treated as one person's worth of data"
             if not tabular else "one table row, i.e. one person's worth of data"),
        ),
        "## Severity of what was found",
        "",
        "Severity = how bad this would be if exposed. It starts from the *kind* of data, then "
        "rises when several identifiers sit together in one record, or when that record is "
        "unique in the dataset. It does **not** depend on how confident the scanner is.",
        "",
        *_table(
            [
                [level.value, str(report.severity_histogram.get(level, 0)), LEVEL_MEANING[level]]
                for level in _ORDER
                if report.severity_histogram.get(level, 0)
            ],
            ["Severity", "Findings", "What it means"],
        ),
        "",
    ]

    if report.heatmap:
        lines += [
            "## Where the risk is",
            "",
            "Which columns (or documents) the sensitive data actually sits in — so you know "
            "where to act first.",
            "",
            *_glossary(
                ("Location", "one column of the table" if tabular else "one document"),
                ("The number", "how many **findings** of that severity sat there — not how "
                 + ("many rows. In a clean table every row has the same columns, so a column "
                    "scanned across 40 rows shows 40"
                    if tabular else
                    "many documents. One document can hold hundreds of findings")),
                ("Blank", "none of that severity here"),
            ),
            *_table(
                [
                    [location] + [str(cells.get(level, "") or "") for level in _ORDER]
                    for location, cells in sorted(
                        report.heatmap.items(),
                        key=lambda kv: -sum(
                            kv[1].get(l, 0) for l in (SeverityLevel.CRITICAL, SeverityLevel.HIGH)
                        ),
                    )
                ],
                ["Location"] + [level.value for level in _ORDER],
            ),
            "",
        ]

    if report.per_entity:
        # A finer entity is reported as the broader one it is_a (a physician as a person),
        # which otherwise makes the data type look less specific than what was actually
        # matched. Name the subtypes so the rollup is visible rather than silent.
        # Keyed on entity *name* to match per_entity, which groups by name so one concept
        # defined in two ontology files stays one row. Keying on entity_id here silently
        # missed every lookup and blanked the column.
        subtypes_by_entity: Dict[str, Counter] = defaultdict(Counter)
        for finding in report.findings:
            subtype = finding.detection.detected_subtype
            if subtype:
                subtypes_by_entity[finding.detection.entity][subtype.split("::")[-1]] += 1

        def _rolled_up_from(entity_id: str) -> str:
            counts = subtypes_by_entity.get(entity_id)
            if not counts:
                return "—"
            return ", ".join(f"{name} ({n})" for name, n in counts.most_common())

        lines += [
            "## Data types / entities identified",
            "",
            "The inventory: which *types* of sensitive data live in this dataset, and how "
            "exposed each type is.",
            "",
            *_glossary(
                ("Data type", "the kind of sensitive data (a name, an email, a zip code)"),
                ("Findings", "how many times it appeared across the whole dataset"),
                ("Worst severity", "the most severe any single one of them reached"),
                ("Typical severity", "their average score, 0 (harmless) to 1 (identifies "
                 "someone outright). Values of the same type usually score alike, so this "
                 "number repeats"),
                ("Rolled up from", "a more specific type that was matched but is reported "
                 "under this broader one (a physician reported as a person). **`—` means "
                 "nothing was rolled up** — the type was matched directly"),
                ("Regulations", "which rules treat this type as regulated data"),
            ),
            *_table(
                [
                    [
                        entity_id.split("::")[-1],
                        str(rollup.count),
                        rollup.max_level.value,
                        f"{rollup.mean_risk_score:.2f}",
                        _rolled_up_from(entity_id),
                        ", ".join(t.value for t in rollup.compliance_tags) or "—",
                    ]
                    for entity_id, rollup in sorted(
                        report.per_entity.items(), key=lambda kv: -kv[1].count
                    )
                ],
                [
                    "Data type",
                    "Findings",
                    "Worst severity",
                    "Typical severity (0–1)",
                    "Rolled up from",
                    "Regulations",
                ],
            ),
            "",
        ]

    if report.per_record:
        riskiest = sorted(
            report.per_record.items(),
            key=lambda kv: (
                -kv[1].strong_identifier_types,
                -_ORDER[::-1].index(kv[1].worst_level),
                -(kv[1].risk_mass / max(kv[1].finding_count, 1)),
            ),
        )[:10]
        lines += [
            "## Riskiest records",
            "",
            "The individual people (rows, or documents) most exposed by this dataset. Ranked by "
            "how *concentrated* the risk is, not how much text there is — otherwise the longest "
            "document would always win on volume alone. Showing the top 10; in a uniform table "
            "every row holds the same columns, so many rows tie on an identical score.",
            "",
            *_glossary(
                ("Record", "one table row" if tabular else "one document"),
                ("Composite identifier types", "how many **different kinds** of strong "
                 "identifier sit together here (name + SSN + email = 3). Ten names still "
                 "count as one, because ten names pin down a person no better than one does. "
                 "This is the main ranking: identifiers stacking up is what makes a record "
                 "dangerous"),
                ("Avg severity", "average severity of this record's findings, 0–1"),
                ("Total risk", "those severity scores added up (11 findings averaging 0.73 = "
                 "8.1). It grows with size, so use it to compare records of similar length — "
                 "it is deliberately **not** what ranks this table"),
                ("Findings", "every sensitive value in the record, weak ones included. Always "
                 "≥ composite identifier types, which counts only distinct strong kinds"),
                ("Unique", "**`yes` is bad** — nobody else shares this record's combination of "
                 "traits, so this person can be picked out of the crowd. `no` is safer: they "
                 "blend in with at least one other record"),
            ),
            *_table(
                [
                    [
                        label,
                        str(profile.strong_identifier_types),
                        f"{profile.risk_mass / max(profile.finding_count, 1):.2f}",
                        f"{profile.risk_mass:.1f}",
                        str(profile.finding_count),
                        profile.worst_level.value,
                        "yes" if profile.is_singleton else "no",
                    ]
                    for label, profile in riskiest
                ],
                ["Record", "Composite identifier types", "Avg severity", "Total risk",
                 "Findings", "Worst severity", "Unique"],
            ),
            "",
        ]

    found = [(i, s) for i, s in report.hipaa_checklist.items() if s.finding_count]
    if report.hipaa_checklist:
        missing = [i for i, s in report.hipaa_checklist.items() if not s.finding_count]
        lines += [
            "## HIPAA Safe Harbor checklist",
            "",
            "HIPAA lists 18 categories of identifier that must be removed for health data to "
            "count as de-identified. This is which of the 18 appear in your data.",
            "",
            *_table(
                [
                    [i.value.replace("_", " "), str(s.finding_count), ", ".join(s.entities)]
                    for i, s in found
                ],
                ["Identifier category present", "Findings", "Found as"],
            ),
            "",
            f"**Not found ({len(missing)} of 18):** "
            + (", ".join(i.value.replace("_", " ") for i in missing) or "none"),
            "",
            ("> **These are Safe Harbor *identifier types*, not a finding that HIPAA applies.** "
             "HIPAA applies to health data; the same name and phone number in a marketing list "
             "are not HIPAA-regulated. This dataset was not identified as health data, so the "
             "regulatory table below does not tag HIPAA — pass `health_context=True` if it is."
             if not any(r.value == "HIPAA" for r in report.compliance_summary)
             else "> HIPAA is tagged below because this dataset was identified as health data."),
            "",
            "> A category being absent means the scanner found none — not that none exist. "
            "Some categories can only be detected when they appear as text: photographs and "
            "fingerprint scans cannot be, while genetic sequences can.",
            "",
        ]

    if report.compliance_summary:
        lines += [
            "## Regulatory exposure",
            "",
            "Which rulebooks this data falls under, and how much of it each one covers.",
            "",
            *_glossary(
                ("Findings subject to it", "how many of the findings above that regulation "
                 "treats as regulated data. One finding can count under several regulations "
                 "at once, so these columns overlap and will not add up to the total"),
                ("Worst severity", "the most severe finding in that regulation's scope"),
            ),
            *_table(
                [
                    [r.value, str(s.count), s.max_level.value]
                    for r, s in report.compliance_summary.items()
                ],
                ["Regulation", "Findings subject to it", "Worst severity"],
            ),
            "",
            "> **These are counts, not scores** — a bigger number is not automatically worse, "
            "it just reflects how much data of that kind is present.",
            "",
            "> **How the mapping is decided — and how far to trust it.** This is decided by "
            "this scanner's own ontology, not by OpenMed, using one deliberately simple rule: "
            "any data type not marked *neutral* counts as personal data (GDPR + CCPA); a type "
            "classified as health data adds HIPAA; a financial instrument adds PCI.",
            "",
            "> **Reliable:** *is this personal data at all* — that follows directly from the "
            "data type and is dependable. **Not reliable:** *which jurisdiction applies to "
            "you*. The rule tags GDPR and CCPA on every personal-data finding regardless of "
            "whether your subjects are EU or California residents, or whether your business "
            "meets CCPA's thresholds. Read the counts as **\"this much data would be in scope "
            "if that law applies to you\"**, not as a finding that it does. **Not legal "
            "advice** — a lawyer confirms which regimes bind you.",
            "",
        ]

    reid = report.reidentification
    lines += [
        "## Re-identification risk of individuals",
        "",
        "Could someone work out *who* a record belongs to, even after the obvious identifiers "
        "(name, email) are taken away — just by combining ordinary-looking fields like city, "
        "zip code and visit date? This measures the data **as scanned, before any scrubbing**.",
        "",
    ]
    if reid is None:
        lines += [
            f"**Not measured.** Re-identifiability is a comparison *between* records — you need "
            f"a crowd before you can ask whether someone stands out in it. "
            f"{breakdown.record_count} record(s) were scanned, below the minimum of "
            f"{breakdown.min_population}, so no honest number can be given.",
            "",
        ]
    else:
        share, verdict = _reid_verdict(reid)
        lines += [
            f"### {share} of records can be singled out — **{verdict}**",
            "",
            f"- **{reid.records_below_k_threshold} of {reid.record_count} records** sit below "
            f"the k={reid.k_threshold} bar used to call data de-identified.",
            f"- **{reid.singleton_count}** are completely one of a kind (nobody else matches "
            "them at all).",
            f"- **Smallest crowd size (k) = {reid.k_min}.**",
            f"- Compared on these traits: **{', '.join(reid.quasi_identifiers) or '—'}**",
            "- Values that would be exposed: **"
            + (", ".join(reid.sensitive_attributes) or "none identified")
            + "**",
            "",
            f"**What k means.** k is the size of the crowd a person hides in: how many records "
            f"share their exact combination of the traits above. k=1 means that person matches "
            f"nobody else and can be picked out; k={reid.k_threshold} or more is the usual bar "
            "for calling data de-identified. Higher k = safer.",
            "",
            "> These numbers are only as good as the traits listed above. Comparing on one weak "
            "field makes data look safer than it really is.",
            "",
        ]

    lines += _deidentification_lines(reid, report.utility)

    residual = report.residual_severity
    if residual is not None:
        before, after = residual.exposure_index_before, residual.exposure_index_after
        drop = before - after
        verdict = (
            "no measurable improvement — the policy is not removing exposure" if drop <= 0
            else "a small dent; most exposure survives" if drop < before * 0.25
            else "a real reduction" if drop < before * 0.75
            else "nearly all exposure removed"
        )
        lines += [
            "## Exposure before vs after de-identification",
            "",
            "The whole point of applying a policy. Every finding was re-scored against what "
            "the scrub actually left behind — a blanked value carries no risk, a coarsened one "
            "carries only what its remaining precision is worth, a fake-but-realistic value "
            "carries a little because records can still be linked.",
            "",
            f"### {before} → {after} out of 100 — {verdict}",
            "",
            *_table(
                [
                    [
                        level.value,
                        str(residual.severity_before.get(level, 0)),
                        str(residual.severity_after.get(level, 0)),
                    ]
                    for level in _ORDER
                    if residual.severity_before.get(level, 0)
                    or residual.severity_after.get(level, 0)
                ],
                ["Severity", "Findings before", "Findings after"],
            ),
            "",
            "> This is exposure remaining in the **scrubbed** copy. The original data is "
            "unchanged and still carries the number on the left.",
            "",
        ]

    optimization = report.optimization
    if optimization is not None and optimization.overrides:
        lines += [
            "## What the optimizer chose, and why",
            "",
            "You asked for actions to be chosen automatically rather than taken from the "
            "policy profile. Each entity below was given the least destructive action that "
            "still met the privacy target; anything not listed was left as configured.",
            "",
            *_glossary(
                ("Data type", "the kind of data the decision applies to"),
                ("Action chosen", "what will be done to every value of that type"),
                ("Why", "the reason this action was picked over a gentler or harsher one"),
            ),
            *_table(
                [
                    [entity, f"`{action}`", optimization.reasons.get(entity, "—")]
                    for entity, action in sorted(optimization.overrides.items())
                ],
                ["Data type", "Action chosen", "Why"],
            ),
            "",
        ]
        if optimization.achieved_k is not None:
            lines += [
                f"Reached a smallest crowd size of **k={optimization.achieved_k}** after "
                f"testing {optimization.searched_nodes} combinations. Combinations that could "
                "only be more destructive than one already known to work were skipped rather "
                "than measured.",
                "",
            ]

    if report.review_queue:
        # Grouped: 300 rows of near-duplicates is not a work queue. One row per distinct
        # (data type, text) with an occurrence count, and *why* it was flagged — an
        # unverified guess and a context-rescued span need different judgement.
        groups: Dict[Tuple[str, str, str, str, str], int] = {}
        for finding in report.review_queue:
            reason = next(
                (
                    r.rule_id.split(":", 1)[-1]
                    for r in finding.assessment.rule_trace
                    if r.rule_id.startswith("review:")
                ),
                "low_confidence",
            )
            key = (
                finding.assessment.level.value,
                finding.location or "—",
                finding.detection.entity,
                finding.detection.text[:40],
                reason,
            )
            groups[key] = groups.get(key, 0) + 1
        ranked = sorted(groups.items(), key=lambda kv: -kv[1])
        lines += [
            "## Human approval flagged entities",
            "",
            f"**{len(report.review_queue)} findings, {len(groups)} distinct.** These are severe "
            "findings the scanner is **not confident** about, queued for a person to confirm or "
            "reject. Severity and confidence are separate: a name is just as sensitive whether "
            "we are 50% or 99% sure it is a name — so these are never downgraded, only flagged.",
            "",
            *_glossary(
                ("Location", "the exact cell — column and row number — to open"
                 if tabular else "the file this value was found in"),
                ("Text found", "the actual value that needs a human decision"),
                ("Why flagged", "`low_confidence` = the detector was unsure. `rescue` = "
                 "surrounding words rescued a weak match — usually right, but worth a look"),
                ("Times", "how many times this exact value appeared in this location"),
            ),
            *_table(
                [
                    [level, location, entity, f"`{text}`", reason, str(count)]
                    for (level, location, entity, text, reason), count in ranked[:25]
                ],
                ["Severity", "Location", "Data type", "Text found", "Why flagged", "Times"],
            ),
            "",
        ]
        if len(ranked) > 25:
            lines += [f"*…and {len(ranked) - 25} more distinct items.*", ""]

    if report.findings:
        worst = max(report.findings, key=lambda f: f.assessment.risk_score)
        lines += [
            "## Worked example: how one score was reached",
            "",
            "Nothing in this report is a black box. Below is the **highest-scoring finding in "
            "this dataset**, opened up step by step, so you can see exactly how a score is "
            "built: it starts from the kind of data, then rises for identifiers stacked in the "
            "same record and for that record being unique. Every finding carries a trace like "
            "this — this is one example, not a special case.",
            "",
            f"`{worst.detection.text[:48]}` — **{worst.detection.entity}**, scored "
            f"**{worst.assessment.risk_score:.2f}** ({worst.assessment.level.value}).",
            "",
            *_glossary(
                ("Stage", "which rule fired — `sensitivity` sets the starting score, "
                 "`cooccurrence` and `reid` raise it, `compliance` only tags regulations"),
                ("What happened", "the rule in plain words"),
                ("Value", "how much that rule moved the score. `—` means it tagged or "
                 "flagged something without changing the number"),
            ),
            *_table(
                [
                    [
                        rule.source,
                        rule.detail,
                        f"{rule.factor:.2f}" if rule.factor is not None else "—",
                    ]
                    for rule in worst.assessment.rule_trace
                ],
                ["Stage", "What happened", "Value"],
            ),
            "",
        ]

    plan = report.policy_plan
    if plan is not None:
        lines += [
            "## Policy plan (what was done to each finding)",
            "",
            "The action taken on every finding, decided by the chosen rulebook. The action "
            "comes from the **kind of data** — its OpenMed label, or failing that its data "
            "class — **not** from its severity score, and not from any optimization: nothing "
            "here searches for a gentler action that would keep more value. That search is a "
            "planned feature; today the profile you pick decides everything.",
            "",
            f"OpenMed profile **`{plan.policy_name}`** — "
            f"{'executed (values rewritten)' if plan.executed else 'planned only (nothing rewritten)'}.",
            "",
            f"- Exact label lookups (`action_for`): **{plan.exact_count}**",
            f"- Class fallback (`policy_label_actions` via seiba `data_class`): "
            f"**{plan.class_fallback_count}**",
            f"- Neutral / missing → keep: **{plan.neutral_keep_count}**",
            "",
            "**Action histogram**",
            "",
            *_table(
                [[action, str(count)] for action, count in plan.action_histogram.items()],
                ["Action", "Findings"],
            ),
            "",
            "**Sample action records**",
            "",
            *_glossary(
                ("Entity", "the kind of data being acted on"),
                ("OpenMed label", "what that maps to in OpenMed's vocabulary — this is what "
                 "the rulebook looks up"),
                ("Policy class", "the fallback bucket used when there is no exact label match"),
                ("Action", "`mask` blanks the value out, `replace` swaps in a realistic fake, "
                 "`hash` turns it into a stable token, `generalize` coarsens it (a date to its "
                 "year, a zip to its region) so it stays usable, `keep` leaves it alone"),
                ("Replacement", "the value actually written in its place"),
            ),
            *_table(
                [
                    [
                        r.entity,
                        r.openmed_label or "—",
                        r.openmed_policy_class or "—",
                        r.action,
                        r.source,
                        (r.execute_fallback or "—"),
                        (r.replacement or "—")[:24] if plan.executed else "—",
                    ]
                    for r in plan.records[:20]
                ],
                [
                    "Entity",
                    "OpenMed label",
                    "Policy class",
                    "Action",
                    "Source",
                    "Execute fallback",
                    "Replacement",
                ],
            ),
            "",
        ]
        if len(plan.records) > 20:
            where = f"`{details_path}`" if details_path else "the JSON companion to this report"
            lines += [
                f"*Showing 20 of {len(plan.records)}. All {len(plan.records)} action records — "
                f"with the full rule trace behind every finding — are in {where}.*",
                "",
            ]

    return "\n".join(lines)


def write_report(
    report: SensitiveDataReadinessReport,
    out_dir: Union[str, Path],
    stem: str,
    *,
    title: str = "Sensitive Data Report",
    scope: Optional[str] = None,
) -> Tuple[Path, Path]:
    """Write ``<stem>.json`` and ``<stem>.md`` into ``out_dir``; returns both paths.

    Writing both together is what lets the markdown cite the JSON that holds every record.
    """
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{stem}.json"
    markdown_path = directory / f"{stem}.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    markdown_path.write_text(
        to_markdown(report, title, scope=scope, details_path=json_path.name), encoding="utf-8"
    )
    return json_path, markdown_path


__all__ = ["to_markdown"]
