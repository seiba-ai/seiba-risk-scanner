"""Public scanner configuration models and backend enums."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Final, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Module-level constants (Final)
# ---------------------------------------------------------------------------

DEFAULT_MIN_FUSED_CONFIDENCE: Final[float] = 0.3
DEFAULT_MIN_CONFIDENCE: Final[float] = 0.0
DEFAULT_PROHIBITED_CONTEXT_WINDOW: Final[int] = 50
DEFAULT_PHRASE_WINDOW_BEFORE: Final[int] = 50
DEFAULT_PHRASE_WINDOW_AFTER: Final[int] = 25
DEFAULT_BEFORE_SIDE_MULTIPLIER: Final[float] = 1.25
DEFAULT_AFTER_SIDE_MULTIPLIER: Final[float] = 1.0
DEFAULT_RESCUE_DET_THRESHOLD: Final[float] = 0.5
DEFAULT_RESCUE_MARGIN: Final[float] = 0.05
DEFAULT_RESCUE_MIN_CANDIDATE_CTX: Final[float] = 0.3
# A context-only hypothesis is capped at base + w_ctx*(1-base) by boost-only fusion, so a
# decisively-named column needs a high base to outrank a confident NER span on that cell.
DEFAULT_DECISIVE_KEY_CANDIDATE_BASE: Final[float] = 0.9
# Compact structured cells lean much harder on the column key than prose does.
DEFAULT_COMPACT_STRUCTURED_KEY_WEIGHT: Final[float] = 0.8
DEFAULT_LLM_SKIP_IF_ABOVE: Final[float] = 0.85
DEFAULT_LLM_CONCURRENCY: Final[int] = 4
DEFAULT_LLM_MODEL: Final[str] = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_FUSION_WEIGHT_DETERMINISTIC: Final[float] = 0.65
DEFAULT_FUSION_WEIGHT_CONTEXTUAL: Final[float] = 0.35
# Single switch back to the legacy overlap passes if election costs accuracy.
DEFAULT_SPAN_ELECTION: Final[bool] = True

ONTOLOGY_STEM_PII: Final[str] = "pii_entity_ontology"
ONTOLOGY_STEM_PHI: Final[str] = "phi_entity_ontology"
ONTOLOGY_STEM_FIN: Final[str] = "fin_entity_ontology"
DEFAULT_ONTOLOGY_STEMS: Final[tuple[str, ...]] = (
    ONTOLOGY_STEM_PII,
    ONTOLOGY_STEM_PHI,
    ONTOLOGY_STEM_FIN,
)


class NERBackendName(StrEnum):
    SPACY = "spacy"
    OPENMED = "openmed"


class LLMBackendName(StrEnum):
    OPENAI = "openai"
    TRANSFORMERS = "transformers"
    OLLAMA = "ollama"
    LLAMA_CPP = "llama_cpp"
    VLLM = "vllm"


class LLMCoverage(StrEnum):
    """Which entity types the LLM stage is asked to cover."""

    GAPS = "gaps"
    FULL = "full"


class ScannerConfig(BaseModel):
    """Validated configuration for :class:`SeibaScanner`."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    verbose: bool = False
    ontology_paths: Optional[List[Union[str, Path]]] = None
    prohibited_context_window: int = Field(
        default=DEFAULT_PROHIBITED_CONTEXT_WINDOW, ge=0
    )
    phrase_window_before: int = Field(default=DEFAULT_PHRASE_WINDOW_BEFORE, ge=0)
    phrase_window_after: int = Field(default=DEFAULT_PHRASE_WINDOW_AFTER, ge=0)
    before_side_multiplier: float = Field(default=DEFAULT_BEFORE_SIDE_MULTIPLIER, gt=0)
    after_side_multiplier: float = Field(default=DEFAULT_AFTER_SIDE_MULTIPLIER, gt=0)
    rescue_det_threshold: float = Field(default=DEFAULT_RESCUE_DET_THRESHOLD, ge=0.0, le=1.0)
    rescue_margin: float = Field(default=DEFAULT_RESCUE_MARGIN, ge=0.0, le=1.0)
    rescue_min_candidate_ctx: float = Field(
        default=DEFAULT_RESCUE_MIN_CANDIDATE_CTX, ge=0.0, le=1.0
    )
    detector_callable: Optional[Callable[..., Any]] = None
    min_confidence: float = Field(default=DEFAULT_MIN_CONFIDENCE, ge=0.0, le=1.0)
    enable_gazetteer: bool = True
    span_election: bool = DEFAULT_SPAN_ELECTION
    skip_ner: bool = False
    ner_runner_override: Optional[Callable[[str], List[Any]]] = None
    ner_backend: NERBackendName = NERBackendName.OPENMED
    ner_model: Optional[str] = None
    llm_backend: Optional[LLMBackendName] = None
    llm_model: Optional[str] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_coverage: LLMCoverage = LLMCoverage.GAPS
    llm_skip_if_above: float = Field(default=DEFAULT_LLM_SKIP_IF_ABOVE, ge=0.0, le=1.0)
    llm_concurrency: int = Field(default=DEFAULT_LLM_CONCURRENCY, ge=1)

    @field_validator("ner_backend", mode="before")
    @classmethod
    def _coerce_ner_backend(cls, value: Any) -> Any:
        if isinstance(value, str):
            return NERBackendName(value)
        return value

    @field_validator("llm_backend", mode="before")
    @classmethod
    def _coerce_llm_backend(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return LLMBackendName(value)
        return value

    @field_validator("llm_coverage", mode="before")
    @classmethod
    def _coerce_llm_coverage(cls, value: Any) -> Any:
        if isinstance(value, str):
            return LLMCoverage(value)
        return value

    @model_validator(mode="after")
    def _default_llm_model(self) -> "ScannerConfig":
        if self.llm_backend is not None and not self.llm_model:
            self.llm_model = DEFAULT_LLM_MODEL
        elif self.llm_backend is None:
            self.llm_model = None
        return self

    def fusion_config(
        self,
        *,
        min_fused_confidence: float = DEFAULT_MIN_FUSED_CONFIDENCE,
        fusion_weight_deterministic: float = DEFAULT_FUSION_WEIGHT_DETERMINISTIC,
        fusion_weight_contextual: float = DEFAULT_FUSION_WEIGHT_CONTEXTUAL,
        extra_before_text: Optional[str] = None,
        extra_after_text: Optional[str] = None,
        provenance_if_no_det: Optional[dict[str, Any]] = None,
        decisive_key_entity_id: Optional[str] = None,
    ) -> "FusionConfig":
        return FusionConfig(
            min_fused_confidence=min_fused_confidence,
            fusion_weight_deterministic=fusion_weight_deterministic,
            fusion_weight_contextual=fusion_weight_contextual,
            context_window_before=self.phrase_window_before,
            context_window_after=self.phrase_window_after,
            extra_before_text=extra_before_text,
            extra_after_text=extra_after_text,
            provenance_if_no_det=provenance_if_no_det,
            decisive_key_entity_id=decisive_key_entity_id,
            span_election=self.span_election,
            rescue_det_threshold=self.rescue_det_threshold,
            rescue_margin=self.rescue_margin,
            rescue_min_candidate_ctx=self.rescue_min_candidate_ctx,
        )


class FusionConfig(BaseModel):
    """Weights, windows, and rescue knobs for deterministic+NER merge."""

    model_config = ConfigDict(extra="forbid")

    min_fused_confidence: float = Field(default=DEFAULT_MIN_FUSED_CONFIDENCE, ge=0.0, le=1.0)
    fusion_weight_deterministic: float = Field(
        default=DEFAULT_FUSION_WEIGHT_DETERMINISTIC, ge=0.0, le=1.0
    )
    fusion_weight_contextual: float = Field(
        default=DEFAULT_FUSION_WEIGHT_CONTEXTUAL, ge=0.0, le=1.0
    )
    context_window_before: int = Field(default=DEFAULT_PHRASE_WINDOW_BEFORE, ge=0)
    context_window_after: int = Field(default=DEFAULT_PHRASE_WINDOW_AFTER, ge=0)
    extra_before_text: Optional[str] = None
    extra_after_text: Optional[str] = None
    provenance_if_no_det: Optional[dict[str, Any]] = None
    rescue_det_threshold: float = Field(default=DEFAULT_RESCUE_DET_THRESHOLD, ge=0.0, le=1.0)
    rescue_margin: float = Field(default=DEFAULT_RESCUE_MARGIN, ge=0.0, le=1.0)
    rescue_min_candidate_ctx: float = Field(
        default=DEFAULT_RESCUE_MIN_CANDIDATE_CTX, ge=0.0, le=1.0
    )
    decisive_key_entity_id: Optional[str] = Field(
        default=None,
        description=(
            "Entity a structured column key decisively names. Its context-only "
            "hypothesis enters at decisive_key_candidate_base so the column can "
            "relabel a mislabelled NER span (Austin under 'city' read as a person)."
        ),
    )
    decisive_key_candidate_base: float = Field(
        default=DEFAULT_DECISIVE_KEY_CANDIDATE_BASE, ge=0.0, le=1.0
    )
    span_election: bool = Field(
        default=DEFAULT_SPAN_ELECTION,
        description=(
            "Resolve overlapping spans by cluster election, keeping losers as alternates. "
            "False restores the legacy containment + entity-priority passes, which can "
            "leave an unscrubbable overlap standing."
        ),
    )


class EvalConfig(BaseModel):
    """Eval-only knobs layered on top of :class:`ScannerConfig`."""

    model_config = ConfigDict(extra="forbid")

    gold_dir: Path
    min_fused_confidence: float = Field(default=DEFAULT_MIN_FUSED_CONFIDENCE, ge=0.0, le=1.0)
    warmup: bool = False
    out_dir: Optional[Path] = None
    run_id: Optional[str] = None
    batched: bool = Field(
        default=True,
        description=(
            "Classify every document in one batched pass (same spans, one NER forward "
            "pass). Disable for the per-document per-stage timing breakdown."
        ),
    )
