from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from seiba_risk_scanner.assessment.models import (
    AssessedFinding,
    Regulation,
    ReidSection,
    ResidualSeverity,
    RuleFired,
    SensitiveDataReadinessReport,
    SeverityLevel,
)
from seiba_risk_scanner.assessment.optimize import ActionOptimizer, resolve_config
from seiba_risk_scanner.assessment.report import HIPAA_IDENTIFIER_MAP, ReportBuilder
from seiba_risk_scanner.assessment.residual import residual_risk, residual_score
from seiba_risk_scanner.assessment.resolver import (
    SeverityResolver,
    level_for,
    review_reason,
)
from seiba_risk_scanner.assessment.utility import utility_loss
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    DataClass,
    load_entity_configs,
)
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
    PipelineStageResult,
)
from seiba_risk_scanner.policy.models import ActionRecord, PolicyPlanSection

# Identifiers strong enough that stacking them in one record pins down a person.
STRONG_CLASSES = frozenset(
    {
        DataClass.DIRECT_IDENTIFIER,
        DataClass.GENETIC_DATA,
        DataClass.BIOMETRIC_IDENTIFIER,
        DataClass.FINANCIAL_DATA,
    }
)
# Fields that form the k-anonymity grouping key, vs. the values it protects.
# genetic_data sits in both: it identifies *and* is a protected attribute.
QUASI_CLASSES = frozenset({DataClass.QUASI_IDENTIFIER, DataClass.DEVICE_IDENTIFIER})
SENSITIVE_CLASSES = frozenset({DataClass.SENSITIVE_ATTRIBUTE, DataClass.GENETIC_DATA})
# Corpus context escalates what becomes *more harmful once attributed* — identifiers and the
# sensitive values they attach to. A zip is what makes attribution possible, but the zip
# itself is no more sensitive for it, so quasi/device/low keep their own severity. Without
# this every finding drifted into high and the severity histogram stopped discriminating.
BOOSTABLE_CLASSES = STRONG_CLASSES | SENSITIVE_CLASSES

CRITICAL_THRESHOLD = 0.93
RecordKey = Tuple[int, Any]


class ReadinessAssessor:
    """Second assessment pass: re-scores findings against the rest of the corpus.

    A lone finding tops out at HIGH; CRITICAL is only reachable here, via identifiers
    stacking in one record or that record being unique in the population.
    """

    def __init__(
        self,
        resolver: Optional[SeverityResolver] = None,
        builder: Optional[ReportBuilder] = None,
        *,
        ontology_paths: Optional[Sequence[Any]] = None,
        cooccurrence_threshold: int = 2,
        cooccurrence_step: float = 0.15,
        cooccurrence_cap: float = 0.45,
        singleton_strength: float = 0.20,
        k_threshold: int = 5,
        min_population: int = 10,
        policy: Optional[str] = "hipaa_safe_harbor",
        execute_policy: bool = True,
        action_overrides: Optional[Mapping[str, str]] = None,
        optimize: Any = None,
    ) -> None:
        self.resolver = resolver or SeverityResolver()
        self.builder = builder or ReportBuilder()
        self.configs = load_entity_configs(ontology_paths)
        self.k_threshold = k_threshold
        self.min_population = min_population
        self.cooccurrence_threshold = cooccurrence_threshold
        self.cooccurrence_step = cooccurrence_step
        self.cooccurrence_cap = cooccurrence_cap
        self.singleton_strength = singleton_strength
        self.policy = policy
        self.execute_policy = execute_policy
        self.action_overrides = action_overrides
        self.optimizer_config = resolve_config(optimize)
        self.thresholds = ((SeverityLevel.CRITICAL, CRITICAL_THRESHOLD),) + tuple(
            self.resolver.thresholds
        )

    def assess(
        self,
        results: Union[PipelineStageResult, Sequence[PipelineStageResult]],
        labels: Optional[Sequence[str]] = None,
        health_context: Optional[bool] = None,
        *,
        policy: Optional[str] = None,
        execute_policy: Optional[bool] = None,
    ) -> SensitiveDataReadinessReport:
        """Score every finding, re-score against the corpus, and summarise into a report.

        `labels` names the sources positionally (filenames, table names). Without it records
        fall back to "doc 0"/"row 5", which a reader cannot map back to anything.

        When ``policy`` is set (constructor or call), attach an OpenMed policy action plan.
        Severity scoring is unchanged by policy.
        """
        findings, keys, reid, strong = self.assess_findings(results, health_context)
        record_labels = [self._record_label(key, labels) for key in keys]
        locations = [
            self._location(finding.detection, key, labels)
            for finding, key in zip(findings, keys)
        ]
        # The heatmap groups by column; a reader chasing one flagged value needs the cell.
        findings = [
            finding.model_copy(
                update={"location": self._location(finding.detection, key, labels, precise=True)}
            )
            for finding, key in zip(findings, keys)
        ]
        report = self.builder.build(
            findings,
            record_labels,
            locations,
            reid,
            {self._record_label(key, labels): entities for key, entities in strong.items()},
            self.min_population,
        )
        policy_name = self.policy if policy is None else policy
        do_execute = self.execute_policy if execute_policy is None else execute_policy
        if policy_name:
            from seiba_risk_scanner.policy import PolicyResolver, execute_plan

            overrides = dict(self.action_overrides or {})
            if self.optimizer_config is not None:
                # When asked for, the optimizer decides — its picks sit above the ontology's
                # default_action, and above a caller's map, because it is the caller's ask.
                optimized = ActionOptimizer(self.optimizer_config).optimize(
                    findings, keys, self.configs
                )
                overrides.update(optimized.overrides)
                report.optimization = optimized
            plan = PolicyResolver(
                policy_name, configs=self.configs, action_overrides=overrides
            ).resolve(findings)
            if do_execute:
                plan = execute_plan(plan)
                report.utility = utility_loss(plan.records)
                if report.reidentification is not None:
                    report.reidentification = self._with_residual(
                        report.reidentification, plan, keys
                    )
                report.residual_severity = self._residual_severity(report, plan)
            report.policy_plan = plan
        return report

    def _residual_severity(
        self, report: SensitiveDataReadinessReport, plan: PolicyPlanSection
    ) -> Optional[ResidualSeverity]:
        """Re-score every finding against what the scrub left, and re-run the exposure index.

        The same builder computes both numbers, so before and after are comparable. Post-scrub
        uniqueness comes from the measured ``reid_rate`` — the share of records that can still
        be linked back — standing in for the pre-scrub below-k share.
        """
        if not report.findings or len(plan.records) != len(report.findings):
            return None
        scored: List[AssessedFinding] = []
        for finding, record in zip(report.findings, plan.records):
            score = residual_score(finding.assessment.risk_score, record)
            scored.append(
                finding.model_copy(
                    update={
                        "assessment": finding.assessment.model_copy(
                            update={"risk_score": score, "level": level_for(score, self.thresholds)}
                        )
                    }
                )
            )
        reid = report.reidentification
        after_reid = (
            reid.model_copy(
                update={
                    "records_below_k_threshold": round((reid.reid_rate or 0.0) * reid.record_count)
                }
            )
            if reid is not None and reid.reid_rate is not None
            else reid
        )
        index_after, _ = self.builder._exposure(
            scored, after_reid, report.exposure_breakdown.record_count, self.min_population
        )
        return ResidualSeverity(
            exposure_index_before=report.exposure_index,
            exposure_index_after=index_after,
            severity_before=dict(report.severity_histogram),
            severity_after=self.builder._histogram(scored),
        )

    def _with_residual(
        self,
        reid: ReidSection,
        plan: PolicyPlanSection,
        keys: Sequence[RecordKey],
    ) -> ReidSection:
        """Fill post-scrub reid_rate/leakage_rate from the executed plan.

        k_min stays pre-scrub (it is the severity input); the two rates are the residual
        outcome. Plan records are 1:1 with findings, so keys group them by record.
        """
        groups: Dict[RecordKey, List[ActionRecord]] = defaultdict(list)
        for record, key in zip(plan.records, keys):
            groups[key].append(record)
        residual = residual_risk(list(groups.values()))
        if residual is None:
            return reid
        return reid.model_copy(
            update={
                "reid_rate": residual.reid_rate,
                "leakage_rate": residual.leakage_rate,
            }
        )

    def assess_findings(
        self,
        results: Union[PipelineStageResult, Sequence[PipelineStageResult]],
        health_context: Optional[bool] = None,
    ) -> Tuple[List[AssessedFinding], List[RecordKey], Optional[ReidSection], Dict[RecordKey, set]]:
        if isinstance(results, PipelineStageResult):
            results = [results]

        findings: List[AssessedFinding] = []
        keys: List[RecordKey] = []
        for index, result in enumerate(results):
            for row in result.detections:
                config = self.configs.get(row.entity_id)
                findings.append(
                    AssessedFinding(detection=row, assessment=self.resolver.resolve(row, config))
                )
                keys.append(self._record_key(row, index))

        self._apply_health_context(findings, health_context)
        strong = self._strong_entities(findings, keys)
        reid, singleton_keys = self._uniqueness(findings, keys)
        for position, finding in enumerate(findings):
            if self._data_class(finding.detection) not in BOOSTABLE_CLASSES:
                continue
            types = len(strong.get(keys[position], ()))
            singleton = keys[position] in singleton_keys
            if types >= self.cooccurrence_threshold or singleton:
                findings[position] = self._escalate(finding, types, singleton, reid)
        return findings, keys, reid, strong

    def _apply_health_context(
        self, findings: List[AssessedFinding], declared: Optional[bool] = None
    ) -> None:
        """In a dataset that holds PHI, the Safe Harbor identifiers around it are HIPAA too.

        Per-entity tagging cannot see this: a name is PII in a mailing list and a HIPAA
        identifier in a patient registry. Same entity, different regime — only the corpus
        knows which. Without it a patient registry reported GDPR/CCPA and no HIPAA at all,
        while its own Safe Harbor checklist listed seven categories present.

        Inference only catches datasets that also carry clinical entities. A patient
        registry of name/email/phone/SSN/zip is byte-identical to a marketing list, so the
        caller must say so via `declared` — the scanner genuinely cannot tell.
        """
        health = declared
        if health is None:
            health = any(
                self.configs.get(f.detection.entity_id)
                and self.configs[f.detection.entity_id].classification_category == "PHI"
                for f in findings
            )
        if not health:
            return
        why = "declared health data" if declared else "dataset holds PHI"
        for position, finding in enumerate(findings):
            tags = finding.assessment.compliance_tags
            if Regulation.HIPAA in tags or finding.detection.entity not in HIPAA_IDENTIFIER_MAP:
                continue
            trace = list(finding.assessment.rule_trace) + [
                RuleFired(
                    rule_id="compliance:health_context",
                    source="compliance",
                    detail=f"{why}, so this Safe Harbor identifier is HIPAA-regulated here",
                )
            ]
            findings[position] = finding.model_copy(
                update={
                    "assessment": finding.assessment.model_copy(
                        update={"compliance_tags": [Regulation.HIPAA] + list(tags), "rule_trace": trace}
                    )
                }
            )

    @staticmethod
    def _record_label(key: RecordKey, labels: Optional[Sequence[str]] = None) -> str:
        """Human identity for one record: the caller's source name when supplied."""
        index, row = key
        source = labels[index] if labels and index < len(labels) else None
        if row is None:
            return source or f"doc {index}"
        return f"{source} row {row}" if source else f"row {row}"

    def _location(
        self,
        row: CombinedDetectionRow,
        key: RecordKey,
        labels: Optional[Sequence[str]] = None,
        *,
        precise: bool = False,
    ) -> str:
        """Where a finding sits: the column for structured data, else the document.

        Column beats row for the heatmap — "the ssn column is where criticals live" is the
        insight; per-record already answers which rows are hot. ``precise`` adds the row back
        so a single flagged value can be located in the source ("email (row 3)").
        """
        provenance = row.provenance or {}
        column = provenance.get("column") or provenance.get("key")
        if column is None:
            return self._record_label(key, labels)
        row_index = provenance.get("row")
        return f"{column} (row {row_index})" if precise and row_index is not None else column

    def _record_key(self, row: CombinedDetectionRow, index: int) -> RecordKey:
        """One person's worth of data: a structured row, else the whole document."""
        provenance = row.provenance or {}
        return (index, provenance.get("row"))

    def _field_name(self, row: CombinedDetectionRow) -> str:
        provenance = row.provenance or {}
        return provenance.get("column") or provenance.get("key") or row.entity

    def _data_class(self, row: CombinedDetectionRow) -> Optional[DataClass]:
        config = self.configs.get(row.entity_id)
        return config.data_class if config else None

    def _strong_entities(
        self, findings: Sequence[AssessedFinding], keys: Sequence[RecordKey]
    ) -> Dict[RecordKey, set]:
        """Distinct strong identifier *types* per record — three names describe one person no
        more precisely than one, but name + SSN + DOB does."""
        strong: Dict[RecordKey, set] = defaultdict(set)
        for finding, key in zip(findings, keys):
            if self._data_class(finding.detection) in STRONG_CLASSES:
                strong[key].add(finding.detection.entity_id)
        return strong

    def _cooccurrence_strength(self, types: int) -> float:
        """Graded but capped: more stacked identifier types pull harder, up to a ceiling."""
        if types < self.cooccurrence_threshold:
            return 0.0
        return min(
            self.cooccurrence_cap,
            self.cooccurrence_step * (types - self.cooccurrence_threshold + 1),
        )

    @staticmethod
    def _toward_ceiling(score: float, strength: float) -> float:
        """Close `strength` of the gap to 1.0.

        Multiplying instead would overshoot: base tops out at 0.90, so a 1.3x co-occurrence
        and 1.2x singleton pinned half of all findings at exactly 1.0 and destroyed ranking
        among criticals. This is monotonic in score, so ordering survives, and it can never
        reach 1.0 — a finding always keeps room to be beaten by a worse one.
        """
        return score + (1.0 - score) * strength

    def _uniqueness(
        self, findings: Sequence[AssessedFinding], keys: Sequence[RecordKey]
    ) -> Tuple[Optional[ReidSection], set]:
        """k-anonymity across records, with our data_class choosing the quasi-identifiers.

        Needs a population: a single record has nothing to be unique against, so we report
        nothing rather than a fabricated k.
        """
        records: Dict[RecordKey, Dict[str, str]] = defaultdict(dict)
        quasi: set[str] = set()
        sensitive: set[str] = set()
        for finding, key in zip(findings, keys):
            data_class = self._data_class(finding.detection)
            if data_class not in QUASI_CLASSES and data_class not in SENSITIVE_CLASSES:
                continue
            field = self._field_name(finding.detection)
            records[key][field] = finding.detection.text
            (quasi if data_class in QUASI_CLASSES else sensitive).add(field)

        # All-or-nothing: below a real population "unique" is trivially true, so we neither
        # report k nor let it move severity. Measuring for scoring while calling it unmeasured
        # in the index was incoherent.
        ordered = sorted(records, key=lambda k: (k[0], str(k[1])))
        if len(ordered) < max(2, self.min_population) or not quasi:
            return None, set()

        from openmed.risk import kanon_report  # heavy import, only needed here

        report = kanon_report(
            [records[key] for key in ordered],
            quasi_identifiers=sorted(quasi),
            sensitive_attributes=sorted(sensitive),
        )
        singletons = {
            ordered[member]
            for klass in report["equivalence_classes"]
            if klass["size"] == 1
            for member in klass["members"]
        }
        below = sum(
            klass["size"] for klass in report["equivalence_classes"] if klass["size"] < self.k_threshold
        )
        # reid_rate/leakage_rate need an original+aux dataset to compare against; left None
        # rather than reporting the 0.0 OpenMed returns when it has nothing to compare.
        return (
            ReidSection(
                k_min=report["k"],
                singleton_count=len(singletons),
                record_count=len(ordered),
                k_threshold=self.k_threshold,
                records_below_k_threshold=below,
                quasi_identifiers=sorted(quasi),
                sensitive_attributes=sorted(sensitive),
            ),
            singletons,
        )

    def _escalate(
        self,
        finding: AssessedFinding,
        types: int,
        singleton: bool,
        reid: Optional[ReidSection],
    ) -> AssessedFinding:
        assessment = finding.assessment
        trace = list(assessment.rule_trace)
        score = assessment.risk_score

        strength = self._cooccurrence_strength(types)
        if strength:
            score = self._toward_ceiling(score, strength)
            trace.append(
                RuleFired(
                    rule_id="cooccurrence",
                    source="cooccurrence",
                    detail=f"{types} strong identifier types stacked in one record: "
                    f"closes {strength:.0%} of the gap to 1.0",
                    factor=strength,
                )
            )
        if singleton:
            score = self._toward_ceiling(score, self.singleton_strength)
            fields = ", ".join(reid.quasi_identifiers) if reid else "?"
            trace.append(
                RuleFired(
                    rule_id="reid:singleton",
                    source="reid",
                    detail=f"record is unique on {fields} (k=1): "
                    f"closes {self.singleton_strength:.0%} of the gap to 1.0",
                    factor=self.singleton_strength,
                )
            )
        # Re-run the review rule now the level has settled: context can lift a finding into
        # HIGH that was not review-eligible on its own.
        level = level_for(score, self.thresholds)
        reason = review_reason(
            level,
            assessment.confidence,
            finding.detection.rescue_applied,
            self.resolver.review_confidence,
        )
        if reason and not assessment.needs_review:
            trace.append(
                RuleFired(
                    rule_id=f"review:{reason}",
                    source="escalation",
                    detail=f"{level.value} after corpus context, with {reason} - needs a human",
                )
            )

        return finding.model_copy(
            update={
                "assessment": assessment.model_copy(
                    update={
                        "risk_score": score,
                        "level": level,
                        "needs_review": reason is not None,
                        "rule_trace": trace,
                    }
                )
            }
        )


__all__ = ["ReadinessAssessor", "STRONG_CLASSES", "QUASI_CLASSES", "SENSITIVE_CLASSES"]
