"""Resolve OpenMed policy actions for seiba findings (exact label, then data_class)."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Mapping, Optional, Sequence, Union

if TYPE_CHECKING:  # import-time cycle: assessment.models imports policy.models
    from seiba_risk_scanner.assessment.models import AssessedFinding

from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    DEFAULT_ACTION_SENTINEL,
    EntityConfig,
    load_entity_configs,
)
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
    SpanAlternate,
)
from seiba_risk_scanner.policy.bridge import (
    canonical_label_for,
    openmed_policy_class_for,
)
from seiba_risk_scanner.policy.generalize import (
    DEFAULT_LEVELS,
    LABEL_KINDS,
    kind_for_label,
)
from seiba_risk_scanner.policy.models import ActionRecord, PolicyPlanSection

FindingLike = Union[CombinedDetectionRow, "AssessedFinding"]

# Least to most protective. An action outside this ladder is executed as a mask, so it is
# compared as one rather than being treated as unknown-and-therefore-safest.
_ACTION_STRENGTH = ("keep", "generalize", "format_preserve", "replace", "hash", "mask", "redact")


def _action_strength(action: str) -> int:
    return _ACTION_STRENGTH.index(action if action in _ACTION_STRENGTH else "mask")


def _row(finding: FindingLike) -> CombinedDetectionRow:
    from seiba_risk_scanner.assessment.models import AssessedFinding

    if isinstance(finding, AssessedFinding):
        return finding.detection
    return finding


class PolicyResolver:
    """Build an explainable action plan from OpenMed PolicyProfile — no seiba overrides."""

    def __init__(
        self,
        policy_name: str = "hipaa_safe_harbor",
        *,
        configs: Optional[Mapping[str, EntityConfig]] = None,
        action_overrides: Optional[Mapping[str, str]] = None,
    ) -> None:
        from openmed.core.policy import load_policy

        self.policy_name = policy_name
        self.profile = load_policy(policy_name)
        self.configs: Mapping[str, EntityConfig] = configs or load_entity_configs()
        self.action_overrides = dict(action_overrides or {})

    def _override(self, record: ActionRecord) -> ActionRecord:
        """Apply the entity's configured action, if it asks for anything but DEFAULT.

        Read from the entity's ``default_action`` in the ontology YAML — that file is the
        config surface — and overridable per run by ``action_overrides``, which is also the
        seam the future optimizer writes through. ``DEFAULT`` leaves the policy profile's
        decision alone.
        """
        config = self.configs.get(record.entity_id)
        spec = self.action_overrides.get(record.entity) or (
            config.default_action if config else DEFAULT_ACTION_SENTINEL
        )
        if not spec or spec == DEFAULT_ACTION_SENTINEL:
            return record
        action, _, level = spec.partition(":")
        update = {"action": action, "source": "seiba_action_override"}
        if action == "generalize":
            kind = kind_for_label(record.openmed_label)
            if kind is None:
                raise ValueError(
                    f"{record.entity} ({record.openmed_label or 'no label'}) cannot be "
                    f"generalized — only {sorted(set(LABEL_KINDS))} have a defensible ladder"
                )
            update["generalization_level"] = level or DEFAULT_LEVELS[kind]
        update["detail"] = f"{record.detail}; entity config → {spec}"
        return record.model_copy(update=update)

    def _decide(
        self, entity_id: str, detected_subtype: Optional[str]
    ) -> tuple[str, Optional[str], Optional[str], str, str]:
        """Pick (action, openmed_label, policy_class, source, detail) for one entity.

        Exact de_identifier label first, then the data_class fallback, then a neutral keep.
        """
        config = self.configs.get(entity_id)
        data_class = config.data_class if config else None
        dc_value = data_class.value if data_class else None

        # The rolled-up subtype is the more specific entity, so its de_identifier is the
        # more accurate policy mapping when it has one (a physician is de-identified as a
        # clinician, not merely as a person). Falls back to the reported parent.
        subtype_label = (
            canonical_label_for(detected_subtype, self.configs) if detected_subtype else None
        )
        label = subtype_label or canonical_label_for(entity_id, self.configs)
        if label:
            action = self.profile.action_for(label)
            via = (
                f"{detected_subtype} (subtype of {entity_id}) → {label}"
                if subtype_label
                else f"{entity_id} → {label}"
            )
            return action, label, None, "openmed_action_for", (
                f"{via}; {self.profile.name}.action_for → {action}"
            )

        policy_class = openmed_policy_class_for(data_class)
        if policy_class is None:
            return "keep", None, None, "neutral_keep", (
                f"{entity_id} has no OpenMed label; data_class={dc_value or 'missing'} → keep"
            )

        action = (self.profile.policy_label_actions or {}).get(
            policy_class, self.profile.default_action
        )
        return action, None, policy_class, "openmed_policy_label_actions", (
            f"{entity_id} de_identifier=null; "
            f"data_class={dc_value} → {policy_class}; "
            f"{self.profile.name}.policy_label_actions → {action}"
        )

    def resolve_one(self, finding: FindingLike) -> ActionRecord:
        row = _row(finding)
        config = self.configs.get(row.entity_id)
        action, label, policy_class, source, detail = self._decide(
            row.entity_id, row.detected_subtype
        )
        return ActionRecord(
            entity_id=row.entity_id,
            entity=row.entity,
            text=row.text,
            start=row.start,
            end=row.end,
            openmed_label=label,
            seiba_data_class=config.data_class.value if config and config.data_class else None,
            openmed_policy_class=policy_class,
            policy_name=self.profile.name,
            action=action,
            source=source,
            detail=detail,
            provenance=row.provenance,
            origin=row.origin,
        )

    def _escalate(self, record: ActionRecord, row: CombinedDetectionRow) -> ActionRecord:
        """Raise the action to the strongest any span this one beat would have received.

        Election keeps a single span per overlap, so the losers are never scrubbed on their
        own. Without this a canonical mapped to a weaker action than the rival it absorbed
        would leave that identifier *more* exposed for having been contested.
        """
        if not row.alternates:
            return record
        strongest = max(
            (self._alternate_action(alt) for alt in row.alternates),
            key=_action_strength,
            default=record.action,
        )
        if _action_strength(strongest) <= _action_strength(record.action):
            return record
        return record.model_copy(
            update={
                "action": strongest,
                "detail": (
                    f"{record.detail}; escalated → {strongest} for absorbed "
                    f"{', '.join(sorted({a.entity for a in row.alternates}))}"
                ),
            }
        )

    def _alternate_action(self, alternate: SpanAlternate) -> str:
        config = self.configs.get(alternate.entity_id)
        spec = self.action_overrides.get(alternate.entity) or (
            config.default_action if config else DEFAULT_ACTION_SENTINEL
        )
        if spec and spec != DEFAULT_ACTION_SENTINEL:
            return spec.partition(":")[0]
        return self._decide(alternate.entity_id, None)[0]

    def resolve(self, findings: Sequence[FindingLike]) -> PolicyPlanSection:
        records = [
            self._escalate(self._override(self.resolve_one(f)), _row(f)) for f in findings
        ]
        hist = Counter(r.action for r in records)
        return PolicyPlanSection(
            policy_name=self.profile.name,
            records=records,
            action_histogram=dict(sorted(hist.items())),
            exact_count=sum(1 for r in records if r.source == "openmed_action_for"),
            class_fallback_count=sum(
                1 for r in records if r.source == "openmed_policy_label_actions"
            ),
            neutral_keep_count=sum(1 for r in records if r.source == "neutral_keep"),
            executed=False,
        )


__all__ = ["PolicyResolver"]
