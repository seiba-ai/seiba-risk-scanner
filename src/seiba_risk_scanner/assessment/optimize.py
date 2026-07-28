"""Pick the least destructive action per entity that still hits a privacy target.

Output is an ``action_overrides`` map — the same seam a user edits by hand — so the optimizer
adds no new path through policy resolution. It is off unless asked for; when on, its choices
take precedence over the ontology's ``default_action``.

Search cost is kept down by splitting entities on what actually interacts:

* direct/financial/biometric identifiers are decided in closed form — the raw value must not
  survive, and among the actions that guarantee that, one retains the most;
* sensitive and neutral values are left alone — they are the payload, not the identity risk;
* only quasi-identifiers are searched, because only they combine to single someone out.

That search walks the generalization lattice bottom-up and uses its monotonicity — coarsening
never lowers k — to keep only the *minimal* combinations that reach the target, discarding
every node above them unexamined.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import product
from typing import Any, Dict, List, Optional, Sequence, Tuple

from seiba_risk_scanner.assessment.models import AssessedFinding
from seiba_risk_scanner.assessment.utility import (
    DEFAULT_UTILITY_WEIGHTS,
    UtilityWeights,
    utility_loss,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    DataClass,
    EntityConfig,
)
from seiba_risk_scanner.policy.generalize import LADDERS, generalize, kind_for_label
from seiba_risk_scanner.policy.models import ActionRecord

# Identity risk lives here; these must never survive in readable form.
_DIRECT_CLASSES = frozenset(
    {DataClass.DIRECT_IDENTIFIER, DataClass.FINANCIAL_DATA, DataClass.BIOMETRIC_IDENTIFIER}
)
_QUASI_CLASSES = frozenset({DataClass.QUASI_IDENTIFIER, DataClass.DEVICE_IDENTIFIER})


class Privacy(StrEnum):
    """How hard to scrub. Pass one of these to ``optimize=``."""

    MAXIMUM = "maximum"      # safest; nothing stays linkable
    BALANCED = "balanced"    # reach the usual bar, keep whatever survives it
    REQUIRED = "required"    # only what is definitely required: no raw values, nothing more


@dataclass(frozen=True)
class OptimizerConfig:
    """Tuning behind the presets. Pass this to ``optimize=`` instead of a preset to adjust."""

    target_k: int = 5
    prefer_unlinkable: bool = False
    generalize_quasi: bool = True
    weights: UtilityWeights = DEFAULT_UTILITY_WEIGHTS

    @classmethod
    def for_preset(cls, preset: "Privacy") -> "OptimizerConfig":
        if preset is Privacy.MAXIMUM:
            return cls(target_k=10, prefer_unlinkable=True)
        if preset is Privacy.REQUIRED:
            return cls(target_k=1, generalize_quasi=False)
        return cls()


@dataclass
class OptimizerPlan:
    """Chosen action per entity, with the reason for each — the report's explanation."""

    overrides: Dict[str, str] = field(default_factory=dict)
    reasons: Dict[str, str] = field(default_factory=dict)
    achieved_k: Optional[int] = None
    searched_nodes: int = 0


def resolve_config(optimize: Any) -> Optional[OptimizerConfig]:
    """Normalize the single ``optimize=`` argument: None/False off, True means balanced."""
    if optimize is None or optimize is False:
        return None
    if optimize is True:
        return OptimizerConfig.for_preset(Privacy.BALANCED)
    if isinstance(optimize, OptimizerConfig):
        return optimize
    return OptimizerConfig.for_preset(Privacy(optimize))


def _action_ladder(entity: str, label: Optional[str], config: OptimizerConfig) -> List[str]:
    """Candidate actions for a quasi-identifier, least destructive first."""
    ladder = ["keep"]
    kind = kind_for_label(label)
    if kind is not None and config.generalize_quasi:
        ladder += [f"generalize:{level}" for level in LADDERS[kind]]
    ladder.append("mask")
    return ladder


class ActionOptimizer:
    """Choose per-entity actions meeting ``target_k`` while retaining as much as possible."""

    def __init__(self, config: OptimizerConfig) -> None:
        self.config = config

    def optimize(
        self,
        findings: Sequence[AssessedFinding],
        keys: Sequence[Any],
        configs: Dict[str, EntityConfig],
    ) -> OptimizerPlan:
        plan = OptimizerPlan()
        by_entity: Dict[str, List[Tuple[Any, AssessedFinding]]] = defaultdict(list)
        for finding, key in zip(findings, keys):
            by_entity[finding.detection.entity].append((key, finding))
        if not by_entity:
            return plan

        quasi: List[str] = []
        for entity, items in by_entity.items():
            cfg = configs.get(items[0][1].detection.entity_id)
            data_class = cfg.data_class if cfg else None
            if data_class in _DIRECT_CLASSES:
                action = "mask" if self.config.prefer_unlinkable else "hash"
                plan.overrides[entity] = action
                plan.reasons[entity] = (
                    "identifies a person outright, so the raw value cannot survive; "
                    + (
                        "masked so nothing stays linkable"
                        if action == "mask"
                        else "hashed, which hides it but keeps records joinable"
                    )
                )
            elif data_class in _QUASI_CLASSES:
                quasi.append(entity)
            else:
                plan.reasons[entity] = "not an identifier — left as configured"

        if quasi and self.config.target_k > 1:
            self._search(quasi, by_entity, configs, plan)
        else:
            for entity in quasi:
                plan.reasons[entity] = "no crowd-size target to meet — left as configured"
        return plan

    def _columns(
        self,
        quasi: Sequence[str],
        by_entity: Dict[str, List[Tuple[Any, AssessedFinding]]],
        configs: Dict[str, EntityConfig],
    ) -> Tuple[List[Any], Dict[str, List[str]], Dict[str, Dict[str, List[str]]]]:
        """Project records onto their quasi-identifier values once, per candidate action.

        Precomputing here is what keeps the search cheap: a lattice node is then a zip of
        ready-made columns, so no value is ever transformed twice and the full records are
        never copied.
        """
        records = sorted({key for entity in quasi for key, _ in by_entity[entity]}, key=str)
        index = {key: position for position, key in enumerate(records)}
        ladders: Dict[str, List[str]] = {}
        columns: Dict[str, Dict[str, List[str]]] = {}
        for entity in quasi:
            cfg = configs.get(by_entity[entity][0][1].detection.entity_id)
            label = cfg.de_identifier if cfg else None
            ladders[entity] = _action_ladder(entity, label, self.config)
            raw: List[str] = [""] * len(records)
            for key, finding in by_entity[entity]:
                raw[index[key]] = finding.detection.text
            kind = kind_for_label(label)
            per_action: Dict[str, List[str]] = {}
            for action in ladders[entity]:
                if action == "keep":
                    per_action[action] = raw
                elif action.startswith("generalize:") and kind is not None:
                    level = action.split(":", 1)[1]
                    per_action[action] = [
                        (generalize(value, kind, level) or "*") if value else "" for value in raw
                    ]
                else:
                    per_action[action] = ["*"] * len(records)
            columns[entity] = per_action
        return records, ladders, columns

    def _retention(
        self,
        entity: str,
        action: str,
        raw: Sequence[str],
        scrubbed: Sequence[str],
    ) -> float:
        """Reuse the report's own retention measure so search and report cannot disagree."""
        rows = [
            ActionRecord(
                entity_id=entity,
                entity=entity,
                text=original,
                start=0,
                end=len(original),
                policy_name="optimizer",
                action=action.split(":", 1)[0],
                source="seiba_action_override",
                detail="",
                replacement=value,
                provenance={"column": entity, "row": position},
            )
            for position, (original, value) in enumerate(zip(raw, scrubbed))
            if original
        ]
        loss = utility_loss(rows, self.config.weights)
        return 1.0 - loss.overall if loss else 1.0

    def _search(
        self,
        quasi: List[str],
        by_entity: Dict[str, List[Tuple[Any, AssessedFinding]]],
        configs: Dict[str, EntityConfig],
        plan: OptimizerPlan,
    ) -> None:
        """Walk the lattice bottom-up, keeping only minimal nodes that reach ``target_k``.

        Coarsening never lowers k, so once a combination succeeds every combination above it
        succeeds too and retains strictly less — those are dominated and never scored.
        """
        records, ladders, columns = self._columns(quasi, by_entity, configs)
        retention = {
            entity: {
                action: self._retention(
                    entity, action, columns[entity][ladders[entity][0]], values
                )
                for action, values in columns[entity].items()
            }
            for entity in quasi
        }
        weight = {entity: len(by_entity[entity]) for entity in quasi}
        total_weight = sum(weight.values()) or 1

        def k_for(node: Tuple[int, ...]) -> int:
            groups: Dict[Tuple[str, ...], int] = defaultdict(int)
            picked = [columns[e][ladders[e][i]] for e, i in zip(quasi, node)]
            for position in range(len(records)):
                groups[tuple(column[position] for column in picked)] += 1
            return min(groups.values()) if groups else 0

        def score(node: Tuple[int, ...]) -> float:
            return sum(
                retention[e][ladders[e][i]] * weight[e] for e, i in zip(quasi, node)
            ) / total_weight

        minimal: List[Tuple[int, ...]] = []
        nodes = sorted(
            product(*[range(len(ladders[e])) for e in quasi]), key=lambda n: (sum(n), n)
        )
        for node in nodes:
            # Dominated: a less-generalized node already met the target, so this one only
            # destroys more. Monotonicity makes skipping it safe without measuring.
            if any(all(a <= b for a, b in zip(found, node)) for found in minimal):
                continue
            plan.searched_nodes += 1
            if k_for(node) >= self.config.target_k:
                minimal.append(node)

        if not minimal:
            best = tuple(len(ladders[e]) - 1 for e in quasi)  # fully generalized still short
            note = "even the strongest setting could not reach the target"
        else:
            best = max(minimal, key=score)
            note = ""
        plan.achieved_k = k_for(best)
        for entity, position in zip(quasi, best):
            action = ladders[entity][position]
            plan.overrides[entity] = action
            plan.reasons[entity] = (
                f"combines with other fields to single people out; {action} reaches "
                f"k={plan.achieved_k} (target {self.config.target_k})"
                + (f" — {note}" if note else "")
            )


__all__ = [
    "ActionOptimizer",
    "OptimizerConfig",
    "OptimizerPlan",
    "Privacy",
    "resolve_config",
]
