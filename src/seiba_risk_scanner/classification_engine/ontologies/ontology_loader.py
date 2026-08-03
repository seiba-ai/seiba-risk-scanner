from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

import yaml

from seiba_risk_scanner.classification_engine.deterministic_detectors.validators_config import (
    ValidatorName,
    get_validator_function,
)
from seiba_risk_scanner.config import DEFAULT_ONTOLOGY_STEMS


class DataClass(str, Enum):
    """Policy-legible data class per entity (replaces High/Medium/Low sensitivity).

    Doubles as the severity anchor and the direct/quasi signal the reid pass needs.
    """

    DIRECT_IDENTIFIER = "direct_identifier"
    GENETIC_DATA = "genetic_data"
    BIOMETRIC_IDENTIFIER = "biometric_identifier"
    FINANCIAL_DATA = "financial_data"
    SENSITIVE_ATTRIBUTE = "sensitive_attribute"
    DEVICE_IDENTIFIER = "device_identifier"
    QUASI_IDENTIFIER = "quasi_identifier"
    NEUTRAL = "neutral"


DEFAULT_ACTION_SENTINEL = "DEFAULT"
# Mirrors the OpenMed action vocabulary plus the Seiba-owned "generalize".
VALID_ACTIONS = frozenset(
    {DEFAULT_ACTION_SENTINEL, "keep", "mask", "redact", "hash", "replace",
     "format_preserve", "generalize"}
)


def validate_default_action(action: str, entity_name: str, de_identifier: Optional[str]) -> None:
    """Reject a bad ``default_action`` when the ontology loads, not mid-scrub.

    The YAML is the config surface, so a typo there has to fail loudly and say which entity.
    """
    from seiba_risk_scanner.policy.generalize import LADDERS, kind_for_label

    verb, _, level = action.partition(":")
    if verb not in VALID_ACTIONS:
        raise ValueError(
            f"{entity_name}: default_action {action!r} is not one of {sorted(VALID_ACTIONS)}"
        )
    if verb != "generalize":
        return
    kind = kind_for_label(de_identifier)
    if kind is None:
        raise ValueError(
            f"{entity_name}: default_action 'generalize' needs a coarsenable de_identifier "
            f"(dates, ages, zip codes, coordinates); it has {de_identifier!r}"
        )
    if level and level not in LADDERS[kind]:
        raise ValueError(
            f"{entity_name}: generalize level {level!r} is not valid for {kind}; "
            f"use one of {list(LADDERS[kind])}"
        )


def make_entity_id(ontology_label: str, entity_name: str) -> str:
    """Stable key across PII/PHI/FIN files (avoids duplicate YAML entity names overwriting)."""
    return f"{ontology_label}::{entity_name}"


@dataclass
class EntityConfig:
    """
    Lightweight config object for a single ontology entity.

    This is intentionally storage-focused: it mirrors what we read from YAML and
    is consumed by deterministic detectors. No validator functions are imported
    here to avoid circular dependencies.
    """

    entity_id: str
    ontology: str
    name: str
    description: Optional[str]
    accepted_patterns: List[str]
    prohibited_patterns: List[str]
    prohibited_prefix: List[str]
    prohibited_suffix: List[str]
    confidence_weight: Optional[float]
    validator_enum: Optional[ValidatorName]
    validator_confidence_weight: Optional[float]
    validator_primary: bool
    contextual_phrases: List[str]
    contextual_phrases_confidence_weight: Optional[float]
    contextual_window_before: Optional[int]
    contextual_window_after: Optional[int]
    classification_category: Optional[str]
    data_class: Optional[DataClass]
    # OpenMed canonical label for PolicyProfile.action_for (e.g. SSN, PERSON). Null when
    # there is no honest OpenMed equivalent — policy shim falls back via data_class.
    de_identifier: Optional[str]
    # What to do with this entity when a policy runs. "DEFAULT" defers to the chosen policy
    # profile; anything else (keep, mask, hash, generalize:year, ...) is the user's own call,
    # edited straight in the ontology YAML.
    default_action: str
    ner_confidence_weight: Optional[float]
    context_rescue_override: bool = False
    # Pattern -> weight, for accepted_patterns that declared one of their own. Lets a
    # single entity carry formats of differing strength (a bare-digit fallback beside a
    # delimited format) instead of one weight having to cover both.
    pattern_confidence_weights: Dict[str, float] = field(default_factory=dict)
    # entity_id of a broader entity this one is a kind of (a physician is a person). The
    # subtype's patterns and phrases still do the detecting, but the detection is reported
    # as the parent, so a wrong guess about *which kind* of thing this is can never stop it
    # being reported as the kind we are sure about. See resolve_entity_alias.
    is_a: Optional[str] = None
    # entity_id of a broader entity this one legitimately sits *inside* (a ZIP within a
    # street address). Unlike is_a these stay different entities; the relation only says a
    # nested span is the same claim at finer grain, so the wider one may absorb it rather
    # than fight it. See SpanElection.
    part_of: Optional[str] = None
    # Adjacent words that belong inside a span rather than beside it: a title before a
    # physician's name, a facility word after an organisation. Resolved through is_a, so a
    # title declared on physician_names also extends spans reported as person_names.
    affix_prefix: List[str] = field(default_factory=list)
    affix_suffix: List[str] = field(default_factory=list)

    def validates(self, text: str) -> bool:
        """Run this entity's validator over ``text``; entities without one always pass."""
        if self.validator_enum is None:
            return True
        try:
            result = get_validator_function(self.validator_enum)(text)
        except Exception:  # noqa: BLE001
            return False
        return bool(result[0]) if isinstance(result, tuple) and result else bool(result)


def _relation(raw_entity: Dict[str, Any], key: str) -> Optional[str]:
    """Read an ``is_a``/``part_of`` entity_id reference, ignoring blanks."""
    raw = raw_entity.get(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def _parse_accepted_patterns(raw_patterns: Any) -> tuple[List[str], Dict[str, float]]:
    """Split accepted_patterns into the pattern list and any per-pattern weights.

    An entry is either a plain regex string (the entity-wide regex weight applies) or a
    ``{pattern: <regex>, confidence_weight: <float>}`` mapping, which lets one entity hold
    formats of unequal strength.
    """
    patterns: List[str] = []
    weights: Dict[str, float] = {}
    for entry in raw_patterns or []:
        if isinstance(entry, str):
            pattern = entry.strip()
            if pattern:
                patterns.append(pattern)
            continue
        if not isinstance(entry, dict):
            continue
        pattern = str(entry.get("pattern") or "").strip()
        if not pattern:
            continue
        patterns.append(pattern)
        weight = entry.get("confidence_weight")
        if weight is not None:
            try:
                weights[pattern] = float(weight)
            except (TypeError, ValueError):
                pass
    return patterns, weights


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Ontology file {path} must contain a top-level mapping.")
    return data


@lru_cache(maxsize=32)
def load_ontology(path: str | Path, ontology_name: Optional[str] = None) -> Dict[str, EntityConfig]:
    """
    Load a single ontology YAML file into a mapping of entity_id -> EntityConfig.

    Keys are composite ``{ontology_stem}::{entity_name}`` so merges do not drop
    entities that share a name across PII/PHI/FIN files.
    """
    path = Path(path)
    data = _load_yaml(path)

    entities_section = data.get("entities") or {}
    if not isinstance(entities_section, dict):
        raise ValueError(f"'entities' section in {path} must be a mapping.")

    ontology_label = ontology_name or path.stem  # e.g. pii_entity_ontology
    result: Dict[str, EntityConfig] = {}

    for entity_name, raw_entity in entities_section.items():
        if not isinstance(raw_entity, dict):
            continue

        regex_cfg = raw_entity.get("regex_patterns") or {}
        accepted_patterns = regex_cfg.get("accepted_patterns") or []
        prohibited_patterns = regex_cfg.get("prohibited_patterns") or []

        # Normalise to lists of strings (strip: literal block scalars may include stray newlines/spaces).
        # An entry may also be {pattern: <regex>, confidence_weight: <float>} to override the
        # entity-wide weight for that one format.
        accepted_patterns, pattern_confidence_weights = _parse_accepted_patterns(accepted_patterns)
        prohibited_patterns = [
            p.strip() for p in prohibited_patterns if isinstance(p, str) and p.strip()
        ]

        prohibited_prefix_cfg = raw_entity.get("prohibited_prefix") or {}
        prohibited_suffix_cfg = raw_entity.get("prohibited_suffix") or {}

        prohibited_prefix_values = prohibited_prefix_cfg.get("values") or []
        prohibited_suffix_values = prohibited_suffix_cfg.get("values") or []

        prohibited_prefix_values = [v for v in prohibited_prefix_values if isinstance(v, str)]
        prohibited_suffix_values = [v for v in prohibited_suffix_values if isinstance(v, str)]

        confidence_weight = regex_cfg.get("confidence_weight")
        if confidence_weight is not None:
            try:
                confidence_weight = float(confidence_weight)
            except (TypeError, ValueError):
                confidence_weight = None

        validators_cfg = raw_entity.get("validators") or {}
        raw_validator_enum = validators_cfg.get("enum")
        validator_enum: Optional[ValidatorName] = None
        if isinstance(raw_validator_enum, str) and raw_validator_enum.strip():
            try:
                validator_enum = ValidatorName(raw_validator_enum.strip())
            except ValueError as exc:
                raise ValueError(
                    f"Unknown validator enum '{raw_validator_enum}' in {path} "
                    f"entity '{entity_name}'"
                ) from exc

        validator_conf = validators_cfg.get("confidence_weight")
        if validator_conf is not None:
            try:
                validator_conf = float(validator_conf)
            except (TypeError, ValueError):
                validator_conf = None

        validator_primary = validators_cfg.get("primary")
        if isinstance(validator_primary, bool):
            validator_primary_bool = validator_primary
        else:
            validator_primary_bool = False

        ctx_cfg = raw_entity.get("contextual_phrases") or {}
        contextual_values = ctx_cfg.get("values") or []
        contextual_values = [
            v.strip() for v in contextual_values if isinstance(v, str) and v.strip()
        ]
        ctx_conf = ctx_cfg.get("confidence_weight")
        if ctx_conf is not None:
            try:
                ctx_conf = float(ctx_conf)
            except (TypeError, ValueError):
                ctx_conf = None

        win_b = ctx_cfg.get("window_before_chars")
        win_a = ctx_cfg.get("window_after_chars")
        if win_b is not None:
            try:
                win_b = int(win_b)
            except (TypeError, ValueError):
                win_b = None
        if win_a is not None:
            try:
                win_a = int(win_a)
            except (TypeError, ValueError):
                win_a = None

        context_rescue_override = ctx_cfg.get("rescue_override") is True

        is_a = _relation(raw_entity, "is_a")
        part_of = _relation(raw_entity, "part_of")

        affix_cfg = raw_entity.get("affixes") or {}
        affix_prefix = [
            v.strip() for v in (affix_cfg.get("prefix") or []) if isinstance(v, str) and v.strip()
        ]
        affix_suffix = [
            v.strip() for v in (affix_cfg.get("suffix") or []) if isinstance(v, str) and v.strip()
        ]

        class_cfg = raw_entity.get("classification") or {}
        cat = class_cfg.get("category")
        classification_category = cat.strip() if isinstance(cat, str) and cat.strip() else None
        raw_dc = class_cfg.get("data_class")
        try:
            data_class = DataClass(raw_dc.strip()) if isinstance(raw_dc, str) and raw_dc.strip() else None
        except ValueError:
            data_class = None
        ner_w = class_cfg.get("ner_confidence_weight")
        if ner_w is not None:
            try:
                ner_w = float(ner_w)
            except (TypeError, ValueError):
                ner_w = None
        else:
            ner_w = None

        raw_desc = raw_entity.get("description")
        description = raw_desc.strip() if isinstance(raw_desc, str) and raw_desc.strip() else None

        raw_deid = raw_entity.get("de_identifier")
        de_identifier = (
            raw_deid.strip() if isinstance(raw_deid, str) and raw_deid.strip() else None
        )

        raw_action = raw_entity.get("default_action")
        default_action = (
            raw_action.strip() if isinstance(raw_action, str) and raw_action.strip() else "DEFAULT"
        )

        eid = make_entity_id(ontology_label, entity_name)
        validate_default_action(default_action, entity_name, de_identifier)
        result[eid] = EntityConfig(
            entity_id=eid,
            ontology=ontology_label,
            name=entity_name,
            description=description,
            accepted_patterns=accepted_patterns,
            prohibited_patterns=prohibited_patterns,
            prohibited_prefix=prohibited_prefix_values,
            prohibited_suffix=prohibited_suffix_values,
            confidence_weight=confidence_weight,
            validator_enum=validator_enum,
            validator_confidence_weight=validator_conf,
            validator_primary=validator_primary_bool,
            contextual_phrases=contextual_values,
            contextual_phrases_confidence_weight=ctx_conf,
            contextual_window_before=win_b,
            contextual_window_after=win_a,
            classification_category=classification_category,
            data_class=data_class,
            de_identifier=de_identifier,
            default_action=default_action,
            ner_confidence_weight=ner_w,
            context_rescue_override=context_rescue_override,
            pattern_confidence_weights=pattern_confidence_weights,
            is_a=is_a,
            part_of=part_of,
            affix_prefix=affix_prefix,
            affix_suffix=affix_suffix,
        )

    return result


@lru_cache(maxsize=8)
def load_all_ontologies(base_dir: Optional[str | Path] = None) -> Dict[str, EntityConfig]:
    """
    Load PII, PHI, and Financial ontologies and merge into a single mapping.

    Cached: deterministic detection re-reads this per scanned value, and parsing the
    YAMLs each time dominated structured scans. Configs are read-only — do not mutate
    the returned mapping (call ``.cache_clear()`` if ontology files change on disk).
    """
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent
    else:
        base_dir = Path(base_dir)

    paths = [base_dir / f"{stem}.yaml" for stem in DEFAULT_ONTOLOGY_STEMS]

    merged: Dict[str, EntityConfig] = {}
    for p in paths:
        if not p.exists():
            continue
        merged.update(load_ontology(p))

    return merged


PathLike = Union[str, Path]


def load_entity_configs(ontology_paths: Optional[Iterable[PathLike]] = None) -> Dict[str, EntityConfig]:
    """
    Load merged entity configs from bundled ontologies or explicit YAML paths.

    Same merge rules as deterministic detection: ``None`` loads PII, PHI, and FIN
    from ``classification_engine/ontologies/``; explicit paths replace that list.
    """
    if ontology_paths is None:
        return load_all_ontologies()

    merged: Dict[str, EntityConfig] = {}
    for p in ontology_paths:
        merged.update(load_ontology(p))
    return merged


def resolve_entity_alias(entity_id: str, configs: Dict[str, EntityConfig]) -> str:
    """Follow ``is_a`` to the broadest entity this one is a kind of.

    Detection is reported as the parent: a physician is a person, so the physician
    patterns still find the span but it is reported as ``person_names``. Deciding *which
    kind* of person someone is is a guess; deciding that they are a person is not, and a
    wrong guess must never be able to drop the span out of the class we are sure about.

    Unknown parents and reference cycles resolve to the last valid id rather than raising:
    a malformed ontology should degrade to the un-aliased entity, not break scanning.
    """
    seen = {entity_id}
    current = entity_id
    while True:
        cfg = configs.get(current)
        parent = cfg.is_a if cfg is not None else None
        if not parent or parent not in configs or parent in seen:
            return current
        seen.add(parent)
        current = parent


def load_ner_label_to_entity_map(path: Optional[str | Path] = None) -> Dict[str, List[str]]:
    """
    Load spaCy / MedspaCy NER label -> ontology ``entity_id`` mapping.

    A label may map to one id (string) or several (list) — e.g. ``NORP`` covers both
    ``nationality`` and ``religious_affiliation``; both are emitted and contextual
    scoring disambiguates. Default path: ``ner_label_to_entity.yaml`` next to this module.
    """
    if path is None:
        path = Path(__file__).resolve().parent / "ner_label_to_entity.yaml"
    else:
        path = Path(path)
    data = _load_yaml(path)
    raw = data.get("mappings") or {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, List[str]] = {}
    for label, eids in raw.items():
        if not isinstance(label, str) or not label.strip():
            continue
        candidates = eids if isinstance(eids, list) else [eids]
        vals = [e.strip() for e in candidates if isinstance(e, str) and e.strip()]
        if vals:
            out[label.strip()] = vals
    return out


__all__ = [
    "EntityConfig",
    "load_ontology",
    "load_all_ontologies",
    "load_entity_configs",
    "load_ner_label_to_entity_map",
    "make_entity_id",
    "resolve_entity_alias",
]

