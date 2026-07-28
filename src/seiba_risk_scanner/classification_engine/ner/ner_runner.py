from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Union

import yaml

from seiba_risk_scanner.classification_engine.ner.backends.base import NERBackend, NerSpanRecord
from seiba_risk_scanner.classification_engine.ner.backends.spacy_backend import (
    DEFAULT_NER_CONFIDENCE_WEIGHT,
    SpaCyBackend,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import EntityConfig
from seiba_risk_scanner.config import NERBackendName

_registry: Dict[tuple, NERBackend] = {}
_registry_lock = threading.Lock()

BACKENDS = tuple(member.value for member in NERBackendName)


def clear_backend_registry() -> None:
    """Drop cached NER backend instances (use between batch model runs)."""
    with _registry_lock:
        _registry.clear()


def _get_backend(name: str, model: Optional[str]) -> NERBackend:
    key = (name, model)
    if key in _registry:
        return _registry[key]
    with _registry_lock:
        if key in _registry:
            return _registry[key]
        try:
            backend_name = NERBackendName(name)
        except ValueError as exc:
            raise ValueError(f"Unknown NER backend: {name!r}. Valid choices: {BACKENDS}") from exc
        if backend_name is NERBackendName.SPACY:
            backend: NERBackend = SpaCyBackend()
        else:  # NERBackendName.OPENMED
            from seiba_risk_scanner.classification_engine.ner.backends.openmed_backend import (
                OpenMedBackend,
            )
            backend = OpenMedBackend(model_name=model)
        _registry[key] = backend
    return backend


def run_combined_ner(
    text: str,
    *,
    configs: Dict[str, EntityConfig],
    backend: str = "spacy",
    model: Optional[str] = None,
    verbose: bool = False,
    timings: Optional[MutableMapping[str, float]] = None,
    # Legacy keyword args — accepted but unused (backend owns its label map now).
    label_map: Optional[Dict[str, str]] = None,
    label_map_path=None,
) -> List[NerSpanRecord]:
    if not text or not isinstance(text, str):
        return []
    return _get_backend(backend, model).run(
        text, configs=configs, verbose=verbose, timings=timings
    )


def _load_label_map(label_map: Union[str, Path, Mapping[str, str]]) -> Dict[str, str]:
    if isinstance(label_map, Mapping):
        raw = label_map
    else:
        raw = yaml.safe_load(Path(label_map).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Custom label_map must be a mapping, got {type(raw).__name__}")
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def make_custom_ner_runner(
    predict: Callable[[str], Iterable[Mapping[str, Any]]],
    label_map: Union[str, Path, Mapping[str, str]],
    *,
    pipeline: str = "custom",
    confidence_weight: float = DEFAULT_NER_CONFIDENCE_WEIGHT,
) -> Callable[[str], List[NerSpanRecord]]:
    """Adapt a raw-label NER model into an ``ner_runner_override``.

    ``predict(text)`` returns spans as mappings with ``start``, ``end``, ``label``
    (or ``entity_group``) and optional ``score``. ``label_map`` maps each raw label
    to an ontology entity_id (a dict, or a path to a YAML of the same); unmapped
    labels are dropped and the span's ontology is taken from the entity_id prefix.
    Use when you have a custom model but would rather hand over a YAML than build
    :class:`NerSpanRecord` objects yourself.
    """
    mapping = _load_label_map(label_map)

    def _run(text: str) -> List[NerSpanRecord]:
        out: List[NerSpanRecord] = []
        for span in predict(text) or []:
            label = span.get("label") or span.get("entity_group")
            start, end = span.get("start"), span.get("end")
            if label is None or start is None or end is None:
                continue
            entity_id = mapping.get(label)
            if entity_id is None:
                continue
            start, end = int(start), int(end)
            out.append(
                NerSpanRecord(
                    start=start,
                    end=end,
                    text=text[start:end],
                    label=label,
                    entity_id=entity_id,
                    confidence_ner=min(1.0, confidence_weight * float(span.get("score", 1.0))),
                    ontology=entity_id.split("::", 1)[0] if "::" in entity_id else None,
                    pipeline=pipeline,
                )
            )
        out.sort(key=lambda r: (r.start, -r.confidence_ner))
        return out

    return _run


def make_hf_ner_runner(
    model_name: str,
    label_map: Union[str, Path, Mapping[str, str]],
    *,
    aggregation_strategy: str = "simple",
    pipeline: str = "hf",
    confidence_weight: float = DEFAULT_NER_CONFIDENCE_WEIGHT,
) -> Callable[[str], List[NerSpanRecord]]:
    """Run any HuggingFace token-classification model as an ``ner_runner_override``.

    seiba builds the HF pipeline (lazily, on first call) and maps each ``entity_group``
    to an ontology entity_id via ``label_map`` (dict or YAML path). This is the
    "bring your own transformer and let seiba run it" path; for non-HF models (GLiNER,
    an API, …) write a ``predict`` and use :func:`make_custom_ner_runner` instead.
    """
    holder: Dict[str, Any] = {}

    def predict(text: str) -> Iterable[Mapping[str, Any]]:
        if "pipe" not in holder:
            from transformers import pipeline as hf_pipeline  # heavy, optional

            holder["pipe"] = hf_pipeline(
                "token-classification", model=model_name, aggregation_strategy=aggregation_strategy
            )
        return holder["pipe"](text) or []

    return make_custom_ner_runner(
        predict, label_map, pipeline=pipeline, confidence_weight=confidence_weight
    )


def run_combined_ner_with_override(
    text: str,
    *,
    configs: Dict[str, EntityConfig],
    override: Optional[Callable[[str], List[NerSpanRecord]]],
    backend: str = "spacy",
    model: Optional[str] = None,
    verbose: bool = False,
    timings: Optional[MutableMapping[str, float]] = None,
) -> List[NerSpanRecord]:
    if override is not None:
        return list(override(text))
    return run_combined_ner(
        text,
        configs=configs,
        backend=backend,
        model=model,
        verbose=verbose,
        timings=timings,
    )
