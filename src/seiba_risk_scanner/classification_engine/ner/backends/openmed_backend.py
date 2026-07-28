from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, MutableMapping, Optional, Tuple

import yaml

from seiba_risk_scanner.classification_engine.ner.backends.base import NERBackend, NerSpanRecord
from seiba_risk_scanner.classification_engine.ner.backends.spacy_backend import DEFAULT_NER_CONFIDENCE_WEIGHT
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import EntityConfig

_LABEL_MAP_PATH = Path(__file__).resolve().parents[1] / "label_maps" / "openmed_labels.yaml"
DEFAULT_PII_MODEL = "OpenMed/OpenMed-PII-SuperClinical-Small-44M-v1"
_PERSON_NAMES_EID = "pii_entity_ontology::person_names"
_GATE_WINDOW = 30  # chars each side of a span searched for require_context keywords
_NER_CACHE_ENTRIES = 2048  # in-process LRU on identical text (repeated tabular cell values)

# label -> (entity_id, require_context keywords, fallback_entity_id). Empty keyword
# tuple => always entity_id; otherwise fallback (or drop when None) if no keyword hit.
_MappedLabel = Tuple[str, Tuple[str, ...], Optional[str]]


class OpenMedBackend(NERBackend):
    """OpenMed SDK backend. PII models use extract_pii + label map; any other
    (e.g. clinical DiseaseDetect) model uses analyze_text with passthrough labels."""

    def __init__(self, model_name: Optional[str] = None, *, use_smart_merging: bool = False) -> None:
        self._model_name = model_name or DEFAULT_PII_MODEL
        self._is_pii = "pii" in self._model_name.lower()
        # OpenMed's regex merge of fragmented spans. Off by default so seiba deterministic
        # owns structured IDs (dates/SSN/phone) instead of competing in fusion.
        self._use_smart_merging = use_smart_merging
        self._config = None
        self._label_map: Dict[str, _MappedLabel] = self._parse_map(
            yaml.safe_load(_LABEL_MAP_PATH.read_text(encoding="utf-8"))
        )

    @property
    def backend_name(self) -> str:
        return "openmed"

    @staticmethod
    def _parse_map(raw: Dict[str, object]) -> Dict[str, _MappedLabel]:
        out: Dict[str, _MappedLabel] = {}
        for label, value in (raw or {}).items():
            if isinstance(value, str):
                out[label] = (value, (), None)
            elif isinstance(value, dict) and value.get("entity_id"):
                ctx = tuple(str(k).lower() for k in value.get("require_context", []))
                fallback = value.get("fallback_entity_id")
                out[label] = (str(value["entity_id"]), ctx, str(fallback) if fallback else None)
        return out

    def _get_config(self):
        if self._config is None:
            from openmed import OpenMedConfig

            # eager: DeBERTa-v3 has no SDPA/flash support. device=auto picks MPS/CUDA
            # when available (output-identical to CPU), else CPU.
            self._config = OpenMedConfig(torch_attention_backend="eager", device="auto")
        return self._config

    def _resolve(self, label: str, text: str, start: int, end: int) -> Optional[str]:
        # PII: map to ontology entity_id (drop unmapped / failed context gate).
        # Clinical: passthrough type label.
        if not self._is_pii:
            return f"openmed::{label}" if label else None
        mapped = self._label_map.get(label)
        if mapped is None:
            return None
        entity_id, require_context, fallback = mapped
        if require_context:
            window = text[max(0, start - _GATE_WINDOW) : end + _GATE_WINDOW].lower()
            if not any(kw in window for kw in require_context):
                return fallback
        return entity_id

    @staticmethod
    def _merge_adjacent_person_names(rows: List[NerSpanRecord], text: str) -> List[NerSpanRecord]:
        """Combine consecutive person-name spans split only by whitespace — OpenMed
        emits first_name/last_name as separate spans (e.g. 'Jennifer' + 'Smith')."""
        person = sorted(
            (r for r in rows if r.entity_id == _PERSON_NAMES_EID), key=lambda r: (r.start, r.end)
        )
        if len(person) <= 1:
            return rows
        other = [r for r in rows if r.entity_id != _PERSON_NAMES_EID]
        merged: List[NerSpanRecord] = []
        cur = person[0]
        for nxt in person[1:]:
            gap = text[cur.end : nxt.start]
            if nxt.start >= cur.end and (not gap or gap.isspace()):
                cur = replace(
                    cur,
                    end=nxt.end,
                    text=text[cur.start : nxt.end],
                    confidence_ner=max(cur.confidence_ner, nxt.confidence_ner),
                )
            else:
                merged.append(cur)
                cur = nxt
        merged.append(cur)
        return other + merged

    def run(
        self,
        text: str,
        *,
        configs: Dict[str, EntityConfig],
        verbose: bool = False,
        timings: Optional[MutableMapping[str, float]] = None,
    ) -> List[NerSpanRecord]:
        if not text or not isinstance(text, str):
            return []

        try:
            from openmed import analyze_text, extract_pii

            t0 = time.perf_counter()
            config = self._get_config()
            if timings is not None:
                timings["ner_nlp_acquire_s"] = timings.get("ner_nlp_acquire_s", 0.0) + (
                    time.perf_counter() - t0
                )

            t1 = time.perf_counter()
            if self._is_pii:
                result = extract_pii(
                    text,
                    model_name=self._model_name,
                    config=config,
                    use_smart_merging=self._use_smart_merging,
                    cache_results=True,
                    max_cache_entries=_NER_CACHE_ENTRIES,
                )
            else:
                result = analyze_text(
                    text,
                    model_name=self._model_name,
                    config=config,
                    cache_results=True,
                    max_cache_entries=_NER_CACHE_ENTRIES,
                )
            if timings is not None:
                timings["ner_tokenize_infer_s"] = timings.get("ner_tokenize_infer_s", 0.0) + (
                    time.perf_counter() - t1
                )

            return self._result_to_records(text, result, configs, verbose)

        except ImportError:
            if verbose:
                print("[NER/openmed] openmed not available; skipping.")
            if timings is not None:
                timings.setdefault("ner_nlp_acquire_s", 0.0)
                timings.setdefault("ner_tokenize_infer_s", 0.0)
            return []
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"[NER/openmed] Error: {exc!r}")
            if timings is not None:
                timings.setdefault("ner_nlp_acquire_s", 0.0)
                timings.setdefault("ner_tokenize_infer_s", 0.0)
            return []

    def _result_to_records(
        self, text: str, result, configs: Dict[str, EntityConfig], verbose: bool
    ) -> List[NerSpanRecord]:
        out: List[NerSpanRecord] = []
        seen: set = set()
        for ent in getattr(result, "entities", []) or []:
            label = getattr(ent, "label", None)
            start, end = getattr(ent, "start", None), getattr(ent, "end", None)
            if label is None or start is None or end is None:
                continue
            start, end = int(start), int(end)
            entity_id = self._resolve(label, text, start, end)
            if entity_id is None:
                if verbose:
                    print(f"[NER/openmed] Dropped label: {label!r}")
                continue
            key = (start, end, entity_id)
            if key in seen:
                continue
            seen.add(key)
            cfg = configs.get(entity_id)
            base = (
                float(cfg.ner_confidence_weight)
                if cfg and cfg.ner_confidence_weight is not None
                else DEFAULT_NER_CONFIDENCE_WEIGHT
            )
            confidence = min(1.0, base * float(getattr(ent, "confidence", 1.0)))
            out.append(
                NerSpanRecord(
                    start=start,
                    end=end,
                    text=text[start:end],
                    label=label,
                    entity_id=entity_id,
                    confidence_ner=confidence,
                    ontology=cfg.ontology if cfg else None,
                    pipeline="openmed",
                )
            )
        out = self._merge_adjacent_person_names(out, text)
        out.sort(key=lambda r: (r.start, -r.confidence_ner))
        return out

    def run_batch(
        self,
        texts: List[str],
        *,
        configs: Dict[str, EntityConfig],
        verbose: bool = False,
        timings: Optional[MutableMapping[str, float]] = None,
    ) -> List[List[NerSpanRecord]]:
        # PII path batches into one forward pass (~15x vs per-text); clinical falls back.
        if not self._is_pii:
            return super().run_batch(texts, configs=configs, verbose=verbose, timings=timings)
        if not texts:
            return []
        try:
            from openmed.core.pii import _extract_pii_batch

            t1 = time.perf_counter()
            results = _extract_pii_batch(
                list(texts),
                model_name=self._model_name,
                config=self._get_config(),
                use_smart_merging=self._use_smart_merging,
            )
            if timings is not None:
                timings["ner_tokenize_infer_s"] = timings.get("ner_tokenize_infer_s", 0.0) + (
                    time.perf_counter() - t1
                )
            return [self._result_to_records(t, r, configs, verbose) for t, r in zip(texts, results)]
        except ImportError:
            if verbose:
                print("[NER/openmed] openmed not available; skipping.")
            return [[] for _ in texts]
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"[NER/openmed] Batch error: {exc!r}")
            return [self.run(t, configs=configs, verbose=verbose) for t in texts]
