"""Predictor adapters: text → PredSpan[] for eval scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, Tuple, runtime_checkable

from seiba_risk_scanner import SeibaScanner
from seiba_risk_scanner.config import ScannerConfig

from eval.types import PredSpan


@runtime_checkable
class Predictor(Protocol):
    def predict(self, text: str, *, min_fused_confidence: float = 0.3) -> List[PredSpan]: ...


@dataclass
class SeibaScannerPredictor:
    """Wraps SeibaScanner; backend choice lives on ScannerConfig."""

    sdk: SeibaScanner

    @classmethod
    def from_scanner_config(cls, scanner_config: ScannerConfig) -> "SeibaScannerPredictor":
        return cls(sdk=SeibaScanner(config=scanner_config))

    @classmethod
    def from_config(cls, **kwargs: Any) -> "SeibaScannerPredictor":
        """Back-compat: build ScannerConfig from keyword args."""
        return cls.from_scanner_config(ScannerConfig(**kwargs))


    def predict(self, text: str, *, min_fused_confidence: float = 0.3) -> List[PredSpan]:
        result = self.sdk.classify_text(text, min_fused_confidence=min_fused_confidence)
        return [PredSpan.from_combined("", row) for row in result.detections]

    def predict_many(
        self,
        texts: List[str],
        docs: List[str],
        *,
        min_fused_confidence: float = 0.3,
    ) -> List[List[PredSpan]]:
        """Predict over every document in one pass, batching NER into a single forward
        pass. Output matches predict_profiled per document; only the timing differs."""
        results = self.sdk.classify_texts(texts, min_fused_confidence=min_fused_confidence)
        return [
            [PredSpan.from_combined(doc, row) for row in result.detections]
            for doc, result in zip(docs, results)
        ]

    def predict_profiled(
        self,
        text: str,
        *,
        doc: str = "",
        min_fused_confidence: float = 0.3,
    ) -> Tuple[List[PredSpan], Dict[str, float]]:
        result, stages = self.sdk.classify_text_profiled(
            text,
            min_fused_confidence=min_fused_confidence,
        )
        return [PredSpan.from_combined(doc, row) for row in result.detections], stages

    def warmup(self, *, min_fused_confidence: float = 0.3) -> None:
        self.sdk.classify_text_profiled("Warmup.", min_fused_confidence=min_fused_confidence)


@dataclass
class OpenMedPredictor:
    """OpenMed PII/clinical adapter. Labels are namespaced as openmed::<label>."""

    model_name: str
    task: str = "pii"
    batch_size: int = 8
    _config: Any = field(default=None, repr=False)
    _processor: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        from eval.openmed_util import openmed_eager_config

        if self._config is None:
            self._config = openmed_eager_config()

    def _ensure_processor(self) -> Any:
        if self._processor is None:
            from openmed import BatchProcessor

            operation = "extract_pii" if self.task == "pii" else "analyze_text"
            self._processor = BatchProcessor(
                model_name=self.model_name,
                operation=operation,
                batch_size=self.batch_size,
                config=self._config,
                continue_on_error=True,
            )
        return self._processor

    @staticmethod
    def spans_from_entities(
        entities: List[Dict[str, Any]],
        *,
        doc: str = "",
    ) -> List[PredSpan]:
        return [
            PredSpan(
                start=int(entity["start"]),
                end=int(entity["end"]),
                text=str(entity["text"]),
                entity_id=f"openmed::{entity['label']}",
                confidence=float(entity.get("confidence") or 0.0),
                provenance={"doc": doc, "openmed_label": entity.get("label")},
            )
            for entity in entities
        ]

    @classmethod
    def preds_by_doc_from_rows(
        cls,
        pred_rows: List[Dict[str, Any]],
        *,
        task: str = "pii",
    ) -> Dict[str, List[PredSpan]]:
        preds_by_doc: Dict[str, List[PredSpan]] = {}
        for row in pred_rows:
            if row.get("task") != task:
                continue
            doc = str(row["doc"])
            preds_by_doc.setdefault(doc, []).append(
                PredSpan(
                    start=int(row["start"]),
                    end=int(row["end"]),
                    text=str(row["text"]),
                    entity_id=f"openmed::{row['label']}",
                    confidence=float(row.get("confidence") or 0.0),
                    provenance={"doc": doc, "openmed_label": row.get("label")},
                )
            )
        return preds_by_doc

    def predict(self, text: str, *, min_fused_confidence: float = 0.3) -> List[PredSpan]:
        """Single-doc predict via a temp file (BatchProcessor is file-oriented)."""
        del min_fused_confidence
        import tempfile
        from pathlib import Path

        from eval.openmed_util import entities_from_result

        processor = self._ensure_processor()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.txt"
            path.write_text(text, encoding="utf-8")
            batch = processor.process_files([str(path)])
            item = batch.items[0]
            if item.error:
                raise RuntimeError(item.error)
            return self.spans_from_entities(entities_from_result(item.result))
