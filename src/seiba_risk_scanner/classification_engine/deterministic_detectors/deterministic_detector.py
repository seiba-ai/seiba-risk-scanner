from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field

from seiba_risk_scanner.classification_engine.ontologies.gazetteer import get_default_index
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    EntityConfig,
    load_entity_configs,
    make_entity_id,
)
from seiba_risk_scanner.classification_engine.deterministic_detectors.validators_config import (
    get_validator_function,
)
from seiba_risk_scanner.config import ONTOLOGY_STEM_PHI

# Gazetteer hits are exact dictionary matches but context-blind, so they enter at a
# moderate base and let contextual scoring confirm or dampen them.
GAZETTEER_CONFIDENCE = 0.6


TextLike = str
PathLike = Union[str, Path]


class DeterministicDetectionRow(BaseModel):
    """Single deterministic span; safe for JSON/API responses."""

    model_config = {"extra": "forbid"}

    entity_id: str = Field(description="Stable id: {ontology_stem}::{entity_name}")
    entity: str = Field(description="Entity key from ontology YAML")
    start: int
    end: int
    text: str
    confidence: float
    ontology: Optional[str] = None
    detected_subtype: Optional[str] = Field(
        default=None,
        description="Finer entity rolled up to an is_a parent, if any (non-lossy rollup).",
    )
    stage: Literal["deterministic"] = "deterministic"
    provenance: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional source (e.g. dataframe row/column) for structured inputs",
    )


class DeterministicStageResult(BaseModel):
    """Result of the deterministic regex + validator pass."""

    model_config = {"extra": "forbid"}

    stage: Literal["deterministic"] = "deterministic"
    detections: List[DeterministicDetectionRow] = Field(default_factory=list)
    text_length: int = 0


DetectionCallable = Callable[
    [TextLike, EntityConfig, Optional[Callable[..., Any]], int],
    List[DeterministicDetectionRow],
]


def _validator_result_to_bool(result: Any) -> bool:
    """
    Normalise different validator return types to a simple boolean.
    """
    if isinstance(result, tuple) and result:
        return bool(result[0])
    return bool(result)


def _compute_confidence(
    config: EntityConfig,
    *,
    has_validator: bool,
    validator_passed: bool,
    pattern: Optional[str] = None,
) -> float:
    """
    Regex match always runs first; then optional validator adjusts score.

    - No validator: ``regex_patterns.confidence_weight`` (default 0.8), unless the matched
      pattern declared its own ``confidence_weight``, which wins.
    - Validator passed: combine regex + ``validators.confidence_weight``; if
      ``validators.primary`` is true, the validator weight dominates.
    - Validator failed: still emit a score by **combining** regex base with the same
      ``validators.confidence_weight`` at lower weight (no separate failed-only knob).
    """
    regex_base = config.confidence_weight if config.confidence_weight is not None else 0.8
    if pattern is not None:
        pattern_weight = config.pattern_confidence_weights.get(pattern)
        if pattern_weight is not None:
            regex_base = pattern_weight

    if not has_validator:
        return regex_base

    v_w = config.validator_confidence_weight
    primary = config.validator_primary

    if validator_passed:
        if primary:
            if v_w is not None:
                return float(v_w)
            return max(regex_base, 0.92)
        if v_w is not None:
            return max(regex_base, float(v_w))
        return max(regex_base, min(regex_base + 0.05, 1.0))

    # Failed: blend regex + validation confidence (weak validator channel).
    if v_w is not None:
        return min(0.85, 0.28 * regex_base + 0.32 * float(v_w))
    return min(0.48, regex_base * 0.55)


def _default_detect_with_config(
    text: TextLike,
    config: EntityConfig,
    validator_fn: Optional[Callable[..., Any]] = None,
    context_window: int = 50,
    provenance: Optional[Dict[str, Any]] = None,
) -> List[DeterministicDetectionRow]:
    """
    Default detection logic using ontology-driven patterns and optional validator.

    - Uses all accepted_patterns as candidate generators.
    - Applies prohibited_prefix / prohibited_suffix as literal context filters.
    - Applies prohibited_patterns as regex filters on the matched span.
    - Applies optional validator_fn on the matched span text (failed validation still
      emits a detection with reduced confidence).
    - Combines regex and validator confidence weights into a single score.
    """
    detections: List[DeterministicDetectionRow] = []

    if not config.accepted_patterns:
        return detections

    prohibited_regexes: List[re.Pattern[str]] = []
    for pattern in config.prohibited_patterns:
        try:
            prohibited_regexes.append(re.compile(pattern))
        except re.error:
            continue

    lower_prohibited_prefix = [p.lower() for p in config.prohibited_prefix]
    lower_prohibited_suffix = [s.lower() for s in config.prohibited_suffix]

    for pattern in config.accepted_patterns:
        try:
            regex = re.compile(pattern)
        except re.error:
            continue

        for match in regex.finditer(text):
            start, end = match.start(), match.end()
            span_text = match.group(0)

            before_ctx = text[max(0, start - context_window) : start]
            after_ctx = text[end : end + context_window]

            before_ctx_lower = before_ctx.lower()
            after_ctx_lower = after_ctx.lower()

            reject = False
            for prefix in lower_prohibited_prefix:
                if prefix and before_ctx_lower.rstrip().endswith(prefix):
                    reject = True
                    break
            if reject:
                continue

            for suffix in lower_prohibited_suffix:
                if suffix and after_ctx_lower.lstrip().startswith(suffix):
                    reject = True
                    break
            if reject:
                continue

            for pregex in prohibited_regexes:
                if pregex.search(span_text):
                    reject = True
                    break
            if reject:
                continue

            validator_passed = True
            if validator_fn is not None:
                try:
                    validator_passed = _validator_result_to_bool(validator_fn(span_text))
                except Exception:
                    validator_passed = False

            confidence = _compute_confidence(
                config,
                has_validator=validator_fn is not None,
                validator_passed=validator_passed,
                pattern=pattern,
            )

            detections.append(
                DeterministicDetectionRow(
                    entity_id=config.entity_id,
                    entity=config.name,
                    start=start,
                    end=end,
                    text=span_text,
                    confidence=confidence,
                    ontology=config.ontology,
                    provenance=provenance,
                )
            )

    return detections


def detect_entities(
    text: TextLike,
    ontology_paths: Optional[Iterable[PathLike]] = None,
    detector_callable: Optional[DetectionCallable] = None,
    context_window: int = 50,
    provenance: Optional[Dict[str, Any]] = None,
) -> List[DeterministicDetectionRow]:
    """
    Run deterministic detection over all ontology-driven entities.

    Confidence is computed per span after regex match: optional validators raise
    scores when they pass; failed validation still yields a combined score from regex
    and ``validators.confidence_weight`` (see ``validators.primary`` for pass dominance).
    Use :func:`deterministic_stage_result` with ``min_confidence`` to filter weak hits.

    Args:
        text: Input text to scan.
        ontology_paths: Optional iterable of explicit ontology YAML paths.
                        If None, defaults to pii/phi/fin ontologies under
                        `classification_engine/ontologies/`.
        detector_callable: Optional custom detector implementation with signature
                           ``(text, config, validator_fn, context_window) -> list``.
                           If provided, ``provenance`` is passed only to the default
                           detector unless your callable forwards it.
        context_window: Characters before/after match for prefix/suffix checks.
        provenance: Optional dict attached to each detection (e.g. structured source).

    Returns:
        Flat list of deterministic detections across all ontologies and entities.
    """
    if not isinstance(text, str) or not text:
        return []

    detector: DetectionCallable = detector_callable or _default_detect_with_config
    entity_configs = load_entity_configs(ontology_paths)

    all_detections: List[DeterministicDetectionRow] = []

    for _, config in entity_configs.items():
        # Sole deterministic entry: ontology must list accepted_patterns (see docstring).
        if not config.accepted_patterns:
            continue

        validator_fn: Optional[Callable[..., Any]] = None
        if config.validator_enum is not None:
            validator_fn = get_validator_function(config.validator_enum)

        if detector is _default_detect_with_config:
            detections = _default_detect_with_config(
                text, config, validator_fn, context_window, provenance
            )
        else:
            detections = detector(text, config, validator_fn, context_window)

        if detections:
            all_detections.extend(detections)

    return all_detections


def gazetteer_detect(
    text: TextLike,
    provenance: Optional[Dict[str, Any]] = None,
) -> List[DeterministicDetectionRow]:
    """Dictionary detection for medical_condition / medication_name via the gazetteer.

    A separate source from regex detection (a 100k-term dictionary cannot ride
    ``accepted_patterns``). The resolved canonical/code ride along in ``provenance``
    so the normalization is non-lossy downstream.
    """
    if not text or not isinstance(text, str):
        return []
    detections: List[DeterministicDetectionRow] = []
    for m in get_default_index().iter_matches(text):
        prov = dict(provenance) if provenance else {}
        prov["gazetteer_canonical"] = m.term.canonical
        if m.term.code:
            prov["gazetteer_code"] = m.term.code
        detections.append(
            DeterministicDetectionRow(
                entity_id=make_entity_id(ONTOLOGY_STEM_PHI, m.term.entity),
                entity=m.term.entity,
                start=m.start,
                end=m.end,
                text=m.text,
                confidence=GAZETTEER_CONFIDENCE,
                ontology=ONTOLOGY_STEM_PHI,
                provenance=prov,
            )
        )
    return detections


def _dedupe_identical_spans_keep_highest_confidence(
    detections: List[DeterministicDetectionRow],
) -> List[DeterministicDetectionRow]:
    """
    Same (start, end) may be labeled as multiple entity types; keep one row with max confidence.
    Equal confidence breaks toward lexicographically greater ``entity_id`` (deterministic).
    """
    best: Dict[Tuple[int, int], DeterministicDetectionRow] = {}
    for d in detections:
        key = (d.start, d.end)
        cur = best.get(key)
        if cur is None:
            best[key] = d
        elif d.confidence > cur.confidence:
            best[key] = d
        elif d.confidence == cur.confidence and d.entity_id > cur.entity_id:
            best[key] = d
    return list(best.values())


def deterministic_stage_result(
    detections: List[DeterministicDetectionRow],
    text_length: int,
    min_confidence: float = 0.0,
) -> DeterministicStageResult:
    """
    Wrap flat detections in a stage result (sorted by start, then confidence).

    ``min_confidence`` drops detections below the threshold after span deduplication
    (e.g. ``0.4`` to exclude weak regex-only hits where validation failed).
    """
    deduped = _dedupe_identical_spans_keep_highest_confidence(detections)
    if min_confidence > 0.0:
        deduped = [d for d in deduped if d.confidence >= min_confidence]
    sorted_rows = sorted(deduped, key=lambda d: (d.start, -d.confidence))
    return DeterministicStageResult(detections=sorted_rows, text_length=text_length)


__all__ = [
    "DeterministicDetectionRow",
    "DeterministicStageResult",
    "DetectionCallable",
    "detect_entities",
    "gazetteer_detect",
    "deterministic_stage_result",
]
