from __future__ import annotations

import re
import threading
import time
from typing import Dict, List, MutableMapping, Optional, Set, Tuple

from seiba_risk_scanner.classification_engine.ner.backends.base import NERBackend, NerSpanRecord
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import EntityConfig, load_ner_label_to_entity_map

DEFAULT_NER_CONFIDENCE_WEIGHT = 0.65

_NUMERIC_DATE_LABELS: frozenset = frozenset({"DATE"})

_DATE_NOISE_RE = re.compile(
    r"^(?:"
    r"\d{1,3}\s+(?:years?|yrs?)(?:\s+old)?\b"
    r"|[A-Z]{2}\s+\d{5}\b"
    r"|(?:daily|weekly|monthly|bi-?weekly|hourly|annually)\b"
    r"|(?:these\s+days?|that\s+day|each\s+month|the\s+1st|the\s+first)\b"
    r"|(?:last\s+4|last\s+four|the\s+free\s+month|free\s+month)\b"
    r")$",
    re.IGNORECASE,
)


def _is_alpha_free(text: str) -> bool:
    return not any(c.isalpha() for c in text)


def _load_en_core_web_sm(spacy_module, *, disable: List[str]):
    """Load ``en_core_web_sm``, downloading it once if it is not installed yet."""
    try:
        return spacy_module.load("en_core_web_sm", disable=disable)
    except OSError:
        from spacy.cli import download

        download("en_core_web_sm")
        return spacy_module.load("en_core_web_sm", disable=disable)


class SpaCyBackend(NERBackend):
    def __init__(self) -> None:
        self._nlp = None
        self._nlp_lock = threading.Lock()
        self._pipeline_kind = "spacy"
        self._label_map: Optional[Dict[str, List[str]]] = None

    @property
    def backend_name(self) -> str:
        return "spacy"

    def _get_nlp(self):
        if self._nlp is not None:
            return self._nlp
        import spacy

        try:
            import medspacy  # noqa: F401

            base = _load_en_core_web_sm(spacy, disable=["parser"])
            self._nlp = medspacy.load(base)
            self._pipeline_kind = "medspacy"
        except ImportError:
            self._nlp = _load_en_core_web_sm(spacy, disable=["parser"])
            self._pipeline_kind = "spacy"
        return self._nlp

    def _get_label_map(self) -> Dict[str, List[str]]:
        if self._label_map is None:
            self._label_map = load_ner_label_to_entity_map()
        return self._label_map

    def _collect_ents(
        self,
        doc,
        *,
        configs: Dict[str, EntityConfig],
        label_map: Dict[str, List[str]],
        seen: Set[Tuple[int, int, str]],
        out: List[NerSpanRecord],
        verbose: bool,
    ) -> None:
        for ent in doc.ents:
            label = ent.label_
            eids = label_map.get(label)
            if not eids:
                if verbose:
                    print(f"[NER/spacy] Unmapped label skipped: {label!r}")
                continue

            span_text = ent.text
            start_char = ent.start_char
            end_char = ent.end_char

            if label in _NUMERIC_DATE_LABELS:
                if _is_alpha_free(span_text):
                    continue
                if _DATE_NOISE_RE.match(span_text.strip()):
                    continue
                if "\n" in span_text:
                    nl_idx = span_text.index("\n")
                    if nl_idx > 0:
                        span_text = span_text[:nl_idx]
                        end_char = start_char + nl_idx

            for eid in eids:
                key = (start_char, end_char, eid)
                if key in seen:
                    continue
                seen.add(key)

                cfg = configs.get(eid)
                confidence = (
                    float(cfg.ner_confidence_weight)
                    if cfg and cfg.ner_confidence_weight is not None
                    else DEFAULT_NER_CONFIDENCE_WEIGHT
                )
                out.append(
                    NerSpanRecord(
                        start=start_char,
                        end=end_char,
                        text=span_text,
                        label=label,
                        entity_id=eid,
                        confidence_ner=confidence,
                        ontology=cfg.ontology if cfg else None,
                        pipeline=self._pipeline_kind,
                    )
                )

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
            import spacy  # noqa: F401
        except ImportError:
            if verbose:
                print("[NER/spacy] spacy not installed; skipping.")
            if timings is not None:
                timings.setdefault("ner_nlp_acquire_s", 0.0)
                timings.setdefault("ner_tokenize_infer_s", 0.0)
            return []

        out: List[NerSpanRecord] = []
        seen: Set[Tuple[int, int, str]] = set()
        label_map = self._get_label_map()

        try:
            with self._nlp_lock:
                t0 = time.perf_counter()
                nlp = self._get_nlp()
                if timings is not None:
                    timings["ner_nlp_acquire_s"] = timings.get("ner_nlp_acquire_s", 0.0) + (
                        time.perf_counter() - t0
                    )
                t1 = time.perf_counter()
                doc = nlp(text)
                self._collect_ents(
                    doc,
                    configs=configs,
                    label_map=label_map,
                    seen=seen,
                    out=out,
                    verbose=verbose,
                )
                if timings is not None:
                    timings["ner_tokenize_infer_s"] = timings.get("ner_tokenize_infer_s", 0.0) + (
                        time.perf_counter() - t1
                    )
        except Exception as exc:  # noqa: BLE001
            if verbose:
                print(f"[NER/spacy] Skipping ({exc!r})")
            if timings is not None:
                timings.setdefault("ner_nlp_acquire_s", 0.0)
                timings.setdefault("ner_tokenize_infer_s", 0.0)

        out.sort(key=lambda r: (r.start, -r.confidence_ner))
        return out
