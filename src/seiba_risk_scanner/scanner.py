from __future__ import annotations

import hashlib
import re
import time
from collections import defaultdict
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import pandas as pd

from seiba_risk_scanner.classification_engine.affix_extend import extend_spans
from seiba_risk_scanner.classification_engine.contextual.contextual_words import (
    ContextualWordsScorer,
    fuse_confidence,
)
from seiba_risk_scanner.classification_engine.deterministic_detectors.deterministic_detector import (
    DeterministicDetectionRow,
    DeterministicStageResult,
    detect_entities,
    deterministic_stage_result,
    gazetteer_detect,
)
from seiba_risk_scanner.classification_engine.llm import llm_runner
from seiba_risk_scanner.classification_engine.ner.backends.base import NerSpanRecord
from seiba_risk_scanner.classification_engine.ner.merge_hypotheses import (
    resolve_deterministic_and_ner_to_combined,
    resolve_overlaps,
)
from seiba_risk_scanner.classification_engine.ner.ner_runner import (
    _get_backend,
    run_combined_ner_with_override,
)
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    EntityConfig,
    load_entity_configs,
)
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
    Origin,
    PipelineStageResult,
)
from seiba_risk_scanner.config import (
    DEFAULT_COMPACT_STRUCTURED_KEY_WEIGHT,
    ScannerConfig,
)

NerRunnerOverride = Optional[Callable[[str], List[NerSpanRecord]]]
StructuredInput = Union[pd.DataFrame, Dict[Any, Any], List[Dict[Any, Any]]]

# NER only contributes names/geo/prose; a value with no ≥2-letter word (pure numeric/ID/
# date/amount cells — the tabular common case) can skip the transformer entirely.
_PROSE_RE = re.compile(r"[A-Za-z]{2,}")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")

# A cell short enough that its column key alone should decide its type — beyond this
# it is prose that NER must still read (a "notes" column, not a "city" column).
_COMPACT_MAX_TOKENS = 4

# Placeholder cells hold no real value, so they neither vote for a column's consensus type
# nor get filled with it: an "N/A" in a name column is not a name, and a masked "****7001"
# or "XXX-XX-6001" is a redaction, not an exposure to flag.
_NULL_CELLS = frozenset({"n/a", "na", "n.a.", "none", "null", "nil", "-", "—", "tbd", "unknown"})
_MASKED_RE = re.compile(r"\*{2,}|[Xx]{3,}|[•#●]{2,}")


def _is_placeholder_cell(text: str) -> bool:
    return text.strip().lower() in _NULL_CELLS or _MASKED_RE.search(text) is not None

# Structural tokens shared across many entity names/aliases (medication_name,
# person_names, phone_number …); too generic to decide a head-noun match on their own.
_GENERIC_KEY_TOKENS = frozenset(
    {"name", "names", "number", "numbers", "code", "codes", "id", "ids", "date",
     "dates", "type", "data", "info", "value", "field"}
)



def _key_tokens(key: str) -> List[str]:
    """Split a column key into lowercase word tokens (snake_case and camelCase)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", key)
    return [t.lower() for t in _WORD_RE.findall(spaced)]


def _decisive_key_entities(
    keys: Iterable[str], configs: Dict[str, EntityConfig]
) -> Dict[str, Optional[str]]:
    """Resolve each column key to the one entity it decisively names, else None.

    Resolution prefers the entity's own name over a mere contextual-phrase mention
    (a ``city`` column, or ``person_city`` by head noun, is the entity *named* city,
    not one that merely lists "city" as context). Within each tier the full token
    phrase is tried before the head noun. Ambiguity at every tier resolves to None so
    NER is left on — a wrong skip suppresses a real span, a missed skip only costs a
    model call.
    """
    name_phrase: Dict[str, set[str]] = {}
    name_token: Dict[str, set[str]] = {}
    ctx_phrase: Dict[str, set[str]] = {}
    ctx_token: Dict[str, set[str]] = {}
    for eid, cfg in configs.items():
        for alias, phrase_map, token_map in (
            (cfg.name, name_phrase, name_token),
            *[(p, ctx_phrase, ctx_token) for p in cfg.contextual_phrases],
        ):
            toks = _key_tokens(alias)
            if not toks:
                continue
            phrase_map.setdefault(" ".join(toks), set()).add(eid)
            for tok in toks:
                if tok not in _GENERIC_KEY_TOKENS:
                    token_map.setdefault(tok, set()).add(eid)

    def resolve(key: str) -> Optional[str]:
        toks = _key_tokens(key)
        if not toks:
            return None
        phrase = " ".join(toks)
        for lookup in (
            name_phrase.get(phrase),
            name_token.get(toks[-1]),
            ctx_phrase.get(phrase),
            ctx_token.get(toks[-1]),
        ):
            if lookup and len(lookup) == 1:
                return next(iter(lookup))
        return None

    return {key: resolve(key) for key in keys}


def _cell_to_str(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    try:
        if pd.isna(raw):
            return None
    except TypeError:
        pass
    value = str(raw).strip()
    return value if value else None


def _synthetic_source_id(prefix: str, content: str) -> str:
    """Name an input the caller did not name: same content always gets the same id."""
    return f"{prefix}-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:12]}"


def _iter_structured_cells(
    data: StructuredInput,
) -> Iterator[Tuple[str, Dict[str, Any], Optional[str]]]:
    if isinstance(data, pd.DataFrame):
        for row_idx, row in data.iterrows():
            for column in data.columns:
                cell_text = _cell_to_str(row[column])
                if cell_text is None:
                    continue
                yield (
                    cell_text,
                    {
                        "kind": "dataframe",
                        "row": int(row_idx) if isinstance(row_idx, (int, float)) else str(row_idx),
                        "column": str(column),
                    },
                    str(column),
                )
        return

    if isinstance(data, dict):
        for key, raw in data.items():
            cell_text = _cell_to_str(raw)
            if cell_text is None:
                continue
            yield cell_text, {"kind": "dict", "key": str(key)}, str(key)
        return

    if isinstance(data, list) and data and isinstance(data[0], dict):
        for row_idx, row in enumerate(data):
            for key, raw in row.items():
                cell_text = _cell_to_str(raw)
                if cell_text is None:
                    continue
                yield (
                    cell_text,
                    {"kind": "list_of_dicts", "row": row_idx, "key": str(key)},
                    str(key),
                )


class SeibaScanner:
    """Ontology-driven PII/PHI/financial span classifier for text and structured data."""

    def __init__(
        self,
        config: Optional[ScannerConfig] = None,
        **kwargs: Any,
    ):
        """Create a scanner from ``ScannerConfig`` or the same fields as keyword args."""
        if config is not None and kwargs:
            raise TypeError("Pass either config= or keyword arguments, not both")
        if config is None:
            config = ScannerConfig(**kwargs)
        self.config = config

        self.verbose = config.verbose
        self.ontology_paths = config.ontology_paths
        self.prohibited_context_window = config.prohibited_context_window
        self.phrase_window_before = config.phrase_window_before
        self.phrase_window_after = config.phrase_window_after
        self.before_side_multiplier = config.before_side_multiplier
        self.after_side_multiplier = config.after_side_multiplier
        self.rescue_det_threshold = config.rescue_det_threshold
        self.rescue_margin = config.rescue_margin
        self.rescue_min_candidate_ctx = config.rescue_min_candidate_ctx
        self.detector_callable = config.detector_callable
        self.min_confidence = config.min_confidence
        self.enable_gazetteer = config.enable_gazetteer
        self.skip_ner = config.skip_ner
        self.ner_runner_override = config.ner_runner_override
        self.ner_backend = config.ner_backend.value
        self.ner_model = config.ner_model
        self.llm_backend = config.llm_backend.value if config.llm_backend else None
        self.llm_model = config.llm_model
        self.llm_base_url = config.llm_base_url
        self.llm_api_key = config.llm_api_key
        self.llm_coverage = config.llm_coverage.value
        self.llm_skip_if_above = config.llm_skip_if_above
        self.llm_concurrency = config.llm_concurrency

        if self.verbose:
            print("Initialized SeibaScanner")

    def _detect_raw(
        self, text: str, provenance: Optional[Dict[str, Any]] = None
    ) -> List[DeterministicDetectionRow]:
        """Regex deterministic detection plus the optional gazetteer dictionary pass."""
        raw = detect_entities(
            text,
            ontology_paths=self.ontology_paths,
            detector_callable=self.detector_callable,
            context_window=self.prohibited_context_window,
            provenance=provenance,
        )
        if self.enable_gazetteer:
            raw += gazetteer_detect(text, provenance)
        return raw

    def _apply_llm_stage(
        self,
        text: str,
        existing: List[CombinedDetectionRow],
        configs: Dict[str, EntityConfig],
        scorer: ContextualWordsScorer,
        *,
        min_fused_confidence: float,
        fusion_weight_deterministic: float,
        fusion_weight_contextual: float,
        stage_timings: Optional[Dict[str, float]] = None,
    ) -> List[CombinedDetectionRow]:
        if self.llm_backend is None or self.llm_model is None:
            return existing
        llm_spans = llm_runner.run_llm_gap_fill(
            text,
            existing=existing,
            backend=self.llm_backend,
            model=self.llm_model,
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            coverage=self.llm_coverage,
            llm_skip_if_above=self.llm_skip_if_above,
            concurrency=self.llm_concurrency,
            verbose=self.verbose,
            timings=stage_timings,
        )
        if not llm_spans:
            return existing

        new_rows: List[CombinedDetectionRow] = []
        for span in llm_spans:
            config = configs.get(span.entity_id)
            if config is None:
                continue
            evidence = scorer.score_span_with_evidence(
                text,
                span.start,
                span.end,
                config,
                self.phrase_window_before,
                self.phrase_window_after,
            )
            fused = fuse_confidence(
                span.confidence_llm,
                evidence.score,
                weight_deterministic=fusion_weight_deterministic,
                weight_contextual=fusion_weight_contextual,
            )
            if fused < min_fused_confidence:
                continue
            new_rows.append(
                CombinedDetectionRow(
                    winner_kind="llm",
                    entity_id=span.entity_id,
                    entity=config.name,
                    start=span.start,
                    end=span.end,
                    text=span.text,
                    confidence=fused,
                    confidence_deterministic=0.0,
                    confidence_ner=None,
                    confidence_llm=span.confidence_llm,
                    confidence_contextual=evidence.score,
                    contextual_matches=evidence.matched_phrases,
                    contextual_matches_before=evidence.matched_in_before,
                    contextual_matches_after=evidence.matched_in_after,
                    ontology=config.ontology,
                    stage="deterministic+ner+contextual",
                )
            )

        if not new_rows:
            return existing

        combined = existing + new_rows
        combined.sort(key=lambda row: (row.start, -row.confidence))
        return resolve_overlaps(combined, configs, span_election=self.config.span_election)

    def _value_is_validated_id(self, text: str, configs: Dict[str, EntityConfig]) -> bool:
        """True when a validator-backed deterministic hit spans the whole value.

        NER cannot change such a cell: validator-lock blocks relabeling and no other
        text remains to scan — so the model call is pure cost (e.g. an ``mrn`` column).
        """
        raw = detect_entities(
            text,
            ontology_paths=self.ontology_paths,
            detector_callable=self.detector_callable,
            context_window=self.prohibited_context_window,
        )
        for d in deterministic_stage_result(
            raw, text_length=len(text), min_confidence=0.0
        ).detections:
            if d.start == 0 and d.end == len(text):
                cfg = configs.get(d.entity_id)
                if cfg is not None and cfg.validator_enum is not None and cfg.validates(d.text):
                    return True
        return False

    def _pipeline_deterministic_ner_contextual(
        self,
        text: str,
        configs: Dict[str, EntityConfig],
        scorer: ContextualWordsScorer,
        *,
        min_fused_confidence: float,
        fusion_weight_deterministic: float,
        fusion_weight_contextual: float,
        extra_before_text: Optional[str] = None,
        extra_after_text: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
        stage_timings: Optional[Dict[str, float]] = None,
        precomputed_ner: Optional[List[NerSpanRecord]] = None,
        decisive_key_entity_id: Optional[str] = None,
    ) -> List[CombinedDetectionRow]:
        t_det0 = time.perf_counter()
        raw = self._detect_raw(text, provenance)
        det_stage = deterministic_stage_result(raw, text_length=len(text), min_confidence=0.0)
        if stage_timings is not None:
            stage_timings["deterministic_s"] = time.perf_counter() - t_det0

        ner_spans: List[NerSpanRecord] = []
        ner_inner: Dict[str, float] = {}
        t_ner0 = time.perf_counter()
        if precomputed_ner is not None:  # batched structured path supplied NER already
            ner_spans = precomputed_ner
        elif not self.skip_ner and _PROSE_RE.search(text):
            ner_spans = run_combined_ner_with_override(
                text,
                configs=configs,
                override=self.ner_runner_override,
                backend=self.ner_backend,
                model=self.ner_model,
                verbose=self.verbose,
                timings=ner_inner if stage_timings is not None else None,
            )
        if stage_timings is not None:
            stage_timings["ner_s"] = time.perf_counter() - t_ner0
            stage_timings["ner_nlp_acquire_s"] = ner_inner.get("ner_nlp_acquire_s", 0.0)
            stage_timings["ner_tokenize_infer_s"] = ner_inner.get("ner_tokenize_infer_s", 0.0)

        t_merge0 = time.perf_counter()
        out = resolve_deterministic_and_ner_to_combined(
            text,
            det_stage,
            ner_spans,
            configs,
            scorer,
            self.config.fusion_config(
                min_fused_confidence=min_fused_confidence,
                fusion_weight_deterministic=fusion_weight_deterministic,
                fusion_weight_contextual=fusion_weight_contextual,
                extra_before_text=extra_before_text,
                extra_after_text=extra_after_text,
                provenance_if_no_det=provenance,
                decisive_key_entity_id=decisive_key_entity_id,
            ),
        )
        if stage_timings is not None:
            stage_timings["merge_contextual_s"] = time.perf_counter() - t_merge0

        if self.llm_backend is not None:
            t_llm0 = time.perf_counter()
            out = self._apply_llm_stage(
                text,
                out,
                configs,
                scorer,
                min_fused_confidence=min_fused_confidence,
                fusion_weight_deterministic=fusion_weight_deterministic,
                fusion_weight_contextual=fusion_weight_contextual,
                stage_timings=stage_timings,
            )
            if stage_timings is not None and "llm_s" not in stage_timings:
                stage_timings["llm_s"] = time.perf_counter() - t_llm0

        return extend_spans(out, text, configs)

    def _make_context_scorer(
        self,
        *,
        contextual_default_weight: float,
        structured_key: Optional[str] = None,
        structured_key_default_weight: float = 0.45,
    ) -> ContextualWordsScorer:
        default_weight = contextual_default_weight
        if structured_key:
            default_weight = max(default_weight, structured_key_default_weight)
        return ContextualWordsScorer(
            default_phrase_weight=default_weight,
            before_side_multiplier=self.before_side_multiplier,
            after_side_multiplier=self.after_side_multiplier,
        )

    def classify_deterministic_text(self, text: str) -> DeterministicStageResult:
        if not text or not isinstance(text, str):
            return DeterministicStageResult(detections=[], text_length=0)

        if self.verbose:
            print(f"Deterministic classification ({len(text)} characters)")

        detections = self._detect_raw(text)
        return deterministic_stage_result(
            detections,
            text_length=len(text),
            min_confidence=self.min_confidence,
        )

    def classify_deterministic_structured(self, data: StructuredInput) -> DeterministicStageResult:
        if data is None:
            return DeterministicStageResult(detections=[], text_length=0)

        all_dets: List[DeterministicDetectionRow] = []
        total_chars = 0
        for cell_text, provenance, _ in _iter_structured_cells(data):
            total_chars += len(cell_text)
            all_dets.extend(self._detect_raw(cell_text, provenance))

        if self.verbose and not all_dets:
            print(f"classify_deterministic_structured: unsupported or empty input ({type(data).__name__})")

        return deterministic_stage_result(
            all_dets,
            text_length=total_chars,
            min_confidence=self.min_confidence,
        )

    def classify_structured_text(
        self,
        data: StructuredInput,
        *,
        source_id: Optional[str] = None,
        source_label: Optional[str] = None,
        min_fused_confidence: float = 0.3,
        fusion_weight_deterministic: float = 0.65,
        fusion_weight_contextual: float = 0.35,
        contextual_default_weight: float = 0.4,
        structured_key_default_weight: float = 0.45,
    ) -> PipelineStageResult:
        if data is None:
            return PipelineStageResult(detections=[], text_length=0)

        configs = load_entity_configs(self.ontology_paths)
        combined: List[CombinedDetectionRow] = []
        cells = list(_iter_structured_cells(data))
        total_chars = sum(len(cell_text) for cell_text, _, _ in cells)

        # A compact cell under a column key that decisively names an entity ("Austin"
        # under "city") is typed by the column, not by what NER guessed the token looks
        # like. Passing the entity into fusion lets it *relabel* the NER span rather than
        # drop it — dropping would leave nothing, since contextual scoring can only
        # rescore an existing span, never create one.
        key_decisive = _decisive_key_entities({k for _, _, k in cells if k}, configs)

        def _decisive_for(cell_text: str, key: Optional[str]) -> Optional[str]:
            if key is None or len(_WORD_RE.findall(cell_text)) > _COMPACT_MAX_TOKENS:
                return None
            return key_decisive.get(key)

        # Batch NER over unique prose cell values in one forward pass (built-in backend
        # only; a user override or skip_ner keeps the per-cell path). Dedup gives repeated
        # values for free; non-prose and validated-id cells skip the model entirely.
        ner_by_text: Dict[str, List[NerSpanRecord]] = {}
        batched = self.ner_runner_override is None and not self.skip_ner
        if batched:
            unique = sorted(
                cell_text
                for cell_text in {ct for ct, _, _ in cells}
                if _PROSE_RE.search(cell_text) and not self._value_is_validated_id(cell_text, configs)
            )
            if unique:
                span_lists = _get_backend(self.ner_backend, self.ner_model).run_batch(
                    unique, configs=configs, verbose=self.verbose
                )
                ner_by_text = dict(zip(unique, span_lists))

        for cell_text, provenance, extra_key in cells:
            decisive = _decisive_for(cell_text, extra_key)
            scorer = self._make_context_scorer(
                contextual_default_weight=contextual_default_weight,
                structured_key=extra_key,
                # A compact key/value pair leans on its column far harder than prose does.
                structured_key_default_weight=(
                    DEFAULT_COMPACT_STRUCTURED_KEY_WEIGHT
                    if decisive is not None
                    else structured_key_default_weight
                ),
            )
            combined.extend(
                self._pipeline_deterministic_ner_contextual(
                    cell_text,
                    configs,
                    scorer,
                    min_fused_confidence=min_fused_confidence,
                    fusion_weight_deterministic=fusion_weight_deterministic,
                    fusion_weight_contextual=fusion_weight_contextual,
                    extra_before_text=extra_key,
                    provenance=provenance,
                    precomputed_ner=ner_by_text.get(cell_text, []) if batched else None,
                    decisive_key_entity_id=decisive,
                )
            )

        combined.extend(self._column_consensus_fills(combined, cells, configs))
        combined.sort(key=lambda row: (row.start, -row.confidence))
        Origin.stamp(
            combined,
            source_id or _synthetic_source_id("table", "\x00".join(c[0] for c in cells)),
            source_label,
        )
        return PipelineStageResult(
            detections=combined,
            text_length=total_chars,
            fusion_weight_deterministic=fusion_weight_deterministic,
            fusion_weight_contextual=fusion_weight_contextual,
        )

    @staticmethod
    def _column_consensus_fills(
        combined: List[CombinedDetectionRow],
        cells: List[Tuple[str, Dict[str, Any], Optional[str]]],
        configs: Dict[str, EntityConfig],
        *,
        min_typed: int = 3,
        dominance: float = 0.7,
    ) -> List[CombinedDetectionRow]:
        """Fill a compact cell the pipeline missed with its column's majority type.

        Structured columns are homogeneous: if nearly all compact values in a column
        resolve to one entity, a lone value the model didn't recognise (a name NER didn't
        know) takes the column's type. Only fills *empty* compact cells — existing
        detections are never overridden — and only on a strong majority, so long-text or
        genuinely mixed columns (a distractor amount column, a free-form notes field) are
        left alone.
        """
        def col(prov: Optional[Dict[str, Any]]) -> Any:
            return (prov or {}).get("column") or (prov or {}).get("key")

        def cell_id(prov: Optional[Dict[str, Any]]) -> Tuple[Any, Any]:
            return (col(prov), (prov or {}).get("row"))

        dets_by_cell: Dict[Tuple[Any, Any], List[CombinedDetectionRow]] = defaultdict(list)
        for d in combined:
            dets_by_cell[cell_id(d.provenance)].append(d)

        compact_by_col: Dict[Any, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
        for text, prov, _ in cells:
            if _is_placeholder_cell(text):
                continue
            if len(_WORD_RE.findall(text)) <= _COMPACT_MAX_TOKENS:
                compact_by_col[col(prov)].append((text, prov))

        fills: List[CombinedDetectionRow] = []
        for column, members in compact_by_col.items():
            dominant_confs: Dict[str, List[float]] = defaultdict(list)
            for text, prov in members:
                for d in dets_by_cell.get(cell_id(prov), []):
                    dominant_confs[d.entity_id].append(d.confidence)
            typed = sum(len(v) for v in dominant_confs.values())
            if typed < min_typed:
                continue
            entity_id, confs = max(dominant_confs.items(), key=lambda kv: len(kv[1]))
            # Dominance among the cells that WERE typed: null placeholders are already out
            # of `members`, so what remains is real values, and a strong agreement there
            # means the column is that type. The untyped remainder are real values the
            # model simply missed (a 2-letter state, an unfamiliar name) — the ones to fill.
            if len(confs) / typed < dominance:
                continue
            cfg = configs.get(entity_id)
            if cfg is None:
                continue
            fill_conf = sum(confs) / len(confs)
            for text, prov in members:
                if dets_by_cell.get(cell_id(prov)):
                    continue  # already typed — never override
                fills.append(
                    CombinedDetectionRow(
                        winner_kind="context_candidate",
                        entity_id=entity_id,
                        entity=cfg.name,
                        start=0,
                        end=len(text),
                        text=text,
                        confidence=fill_conf,
                        confidence_deterministic=0.0,
                        confidence_contextual=0.0,
                        ontology=cfg.ontology,
                        stage="deterministic+ner+contextual",
                        provenance={**prov, "column_consensus": column},
                    )
                )
        return fills

    def classify_text(
        self,
        text: str,
        *,
        source_id: Optional[str] = None,
        source_label: Optional[str] = None,
        min_fused_confidence: float = 0.3,
        fusion_weight_deterministic: float = 0.65,
        fusion_weight_contextual: float = 0.35,
        contextual_default_weight: float = 0.4,
    ) -> PipelineStageResult:
        result, _ = self.classify_text_profiled(
            text,
            source_id=source_id,
            source_label=source_label,
            min_fused_confidence=min_fused_confidence,
            fusion_weight_deterministic=fusion_weight_deterministic,
            fusion_weight_contextual=fusion_weight_contextual,
            contextual_default_weight=contextual_default_weight,
        )
        return result

    def classify_text_profiled(
        self,
        text: str,
        *,
        source_id: Optional[str] = None,
        source_label: Optional[str] = None,
        min_fused_confidence: float = 0.3,
        fusion_weight_deterministic: float = 0.65,
        fusion_weight_contextual: float = 0.35,
        contextual_default_weight: float = 0.4,
    ) -> Tuple[PipelineStageResult, Dict[str, float]]:
        if not text or not isinstance(text, str):
            return PipelineStageResult(detections=[], text_length=0), {}

        if self.verbose:
            print(f"Deterministic + NER + contextual classification ({len(text)} characters)")

        timings: Dict[str, float] = {}
        t0 = time.perf_counter()
        configs = load_entity_configs(self.ontology_paths)
        timings["load_entity_configs_s"] = time.perf_counter() - t0

        t1 = time.perf_counter()
        scorer = self._make_context_scorer(contextual_default_weight=contextual_default_weight)
        timings["scorer_setup_s"] = time.perf_counter() - t1

        combined = self._pipeline_deterministic_ner_contextual(
            text,
            configs,
            scorer,
            min_fused_confidence=min_fused_confidence,
            fusion_weight_deterministic=fusion_weight_deterministic,
            fusion_weight_contextual=fusion_weight_contextual,
            stage_timings=timings,
        )

        combined.sort(key=lambda row: (row.start, -row.confidence))
        Origin.stamp(combined, source_id or _synthetic_source_id("doc", text), source_label)
        return (
            PipelineStageResult(
                detections=combined,
                text_length=len(text),
                fusion_weight_deterministic=fusion_weight_deterministic,
                fusion_weight_contextual=fusion_weight_contextual,
            ),
            timings,
        )

    def classify_texts(
        self,
        texts: List[str],
        *,
        sources: Optional[Sequence[str]] = None,
        min_fused_confidence: float = 0.3,
        fusion_weight_deterministic: float = 0.65,
        fusion_weight_contextual: float = 0.35,
        contextual_default_weight: float = 0.4,
    ) -> List[PipelineStageResult]:
        """Classify many documents, batching NER over unique prose docs into one forward
        pass (~15x on distinct prose vs looping classify_text). Built-in backend only; a
        user override or skip_ner falls back to per-document NER. Result order matches input."""
        configs = load_entity_configs(self.ontology_paths)
        scorer = self._make_context_scorer(contextual_default_weight=contextual_default_weight)

        ner_by_text: Dict[str, List[NerSpanRecord]] = {}
        batched = self.ner_runner_override is None and not self.skip_ner
        if batched:
            unique = sorted({t for t in texts if isinstance(t, str) and _PROSE_RE.search(t)})
            if unique:
                span_lists = _get_backend(self.ner_backend, self.ner_model).run_batch(
                    unique, configs=configs, verbose=self.verbose
                )
                ner_by_text = dict(zip(unique, span_lists))

        results: List[PipelineStageResult] = []
        for index, text in enumerate(texts):
            if not text or not isinstance(text, str):
                results.append(PipelineStageResult(detections=[], text_length=0))
                continue
            combined = self._pipeline_deterministic_ner_contextual(
                text,
                configs,
                scorer,
                min_fused_confidence=min_fused_confidence,
                fusion_weight_deterministic=fusion_weight_deterministic,
                fusion_weight_contextual=fusion_weight_contextual,
                precomputed_ner=ner_by_text.get(text, []) if batched else None,
            )
            combined.sort(key=lambda row: (row.start, -row.confidence))
            source = sources[index] if sources and index < len(sources) else None
            Origin.stamp(combined, source or _synthetic_source_id("doc", text))
            results.append(
                PipelineStageResult(
                    detections=combined,
                    text_length=len(text),
                    fusion_weight_deterministic=fusion_weight_deterministic,
                    fusion_weight_contextual=fusion_weight_contextual,
                )
            )
        return results
